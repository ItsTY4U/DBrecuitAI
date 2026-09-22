from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Job, Application
from .ai import extract_resume_text, analyze_resume
from django.urls import reverse
import json
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required

from django.core.cache import cache
from django.db import IntegrityError
from accounts.models import ApplicantProfile
import threading
from main.rate_limit import check_rate_limit

# Throttles concurrent background Gemini screening calls to prevent 429 Resource Exhausted rate limits
AI_SCREENING_SEMAPHORE = threading.Semaphore(2)

from django.core.paginator import Paginator
from django.views.decorators.cache import cache_control

def jobs(request):
    try:
        query = request.GET.get("q", "").strip()
        department = request.GET.get("department", "").strip()
        page_number = request.GET.get("page", 1)

        is_default_view = not query and not department
        jobs_list = None

        if is_default_view:
            jobs_list = cache.get("default_active_jobs_list")

        if jobs_list is None:
            jobs_qs = Job.objects.filter(status="Active")

            if query:
                jobs_qs = jobs_qs.filter(
                    Q(title__icontains=query) |
                    Q(department__icontains=query)
                )

            if department:
                jobs_qs = jobs_qs.filter(department=department)

            jobs_qs = jobs_qs.only(
                "id", "title", "department", "job_type", "posted_date"
            ).order_by("-posted_date", "-id")

            if is_default_view:
                jobs_list = list(jobs_qs)
                cache.set("default_active_jobs_list", jobs_list, 60)
            else:
                jobs_list = jobs_qs

        paginator = Paginator(jobs_list, 9)
        page_obj = paginator.get_page(page_number)

        context = {
            "jobs": page_obj,
            "page_obj": page_obj,
            "query": query,
            "department": department,
        }

        # Fast partial response for HTMX search / filter requests
        if request.headers.get("HX-Request"):
            return render(
                request,
                "jobs/partials/jobs_list.html",
                context,
            )

        return render(
            request,
            "jobs/jobs.html",
            context,
        )

    except Exception as e:
        import traceback
        return HttpResponse(
            f"<pre>{traceback.format_exc()}</pre>",
            status=500
        )
        
@cache_control(public=True, max_age=30, s_maxage=300, stale_while_revalidate=1800)
def job_detail(request, id):
    cache_key = f"job_detail_{id}"
    job = cache.get(cache_key)
    if job is None:
        job = get_object_or_404(
            Job.objects.prefetch_related("requirements_list"),
            id=id
        )
        cache.set(cache_key, job, 300)
    return render(request, "jobs/job_detail.html", {
        "job": job
    }) 

def _async_screen_application(application_id: int, pre_extracted_text: str = ""):
    """
    Executes resume text extraction and Gemini AI screening asynchronously in a background daemon thread.
    This guarantees that the applicant's submission is instantaneous and never slowed down.
    HR will see the results populated within seconds without any system degradation.
    Throttled by AI_SCREENING_SEMAPHORE to prevent 429 quota exhaustion.
    Delegates directly to screen_application, the Single Source of Truth.
    """
    import logging
    from django.db import connection
    logger = logging.getLogger(__name__)

    with AI_SCREENING_SEMAPHORE:
        try:
            from jobs.models import Application
            from jobs.ai import screen_application

            app = Application.objects.select_related("job", "applicant").filter(id=application_id).first()
            if not app:
                return

            screen_application(app, pre_extracted_text=pre_extracted_text, max_retries=2)

        except Exception as exc:
            logger.error("Unexpected error in background screening worker for app id %s: %s", application_id, exc)
        finally:
            if threading.current_thread() is not threading.main_thread():
                connection.close()


@login_required(login_url="applicant_login")
def apply_job(request, pk):
    job = get_object_or_404(
        Job.objects.prefetch_related("requirements_list"),
        pk=pk,
        status="Active"
    )

    profile, created = ApplicantProfile.objects.get_or_create(
        user=request.user
    )
    
    # Applicant must have an uploaded resume
    if not profile.default_resume:
        return render(
            request,
            "jobs/partials/application_error.html",
            {
                "error": (
                    "Please upload a default resume in your profile before applying."
                )
            }
        )
        
    # GET request
    if request.method == "GET":
        return render(request, "jobs/apply.html", {
            "job": job,
            "profile": profile,
        })
        
    # POST request
    # 1. Rate limiting & spam prevention (strictly 3 per hour per IP & account, with rapid-fire debounce)
    is_limited, limit_err = check_rate_limit(
        request,
        action_key="apply_job",
        limit=3,
        window_seconds=3600,
        account_identifier=request.user.email,
        enable_debounce=True,
        debounce_seconds=3,
    )
    if is_limited:
        return render(request, "jobs/partials/application_error.html", {
            "job": job,
            "profile": profile,
            "error": limit_err,
        }, status=429)

    # 2. Duplicate submission detection (fast indexed check)
    existing_application = Application.objects.filter(
        applicant=request.user,
        job=job
    ).only("id").first()
    
    if existing_application:
        return render(request, "jobs/partials/application_error.html", {
            "job": job,
            "profile": profile,
            "error": "Duplicate submission detected: You have already applied for this job."
        })
        
    try:
        import os
        import threading
        from uuid import uuid4
        from django.core.files.base import ContentFile
        from main.emailer import send_application_submitted_email

        # Capture user-editable fields: first name, last name, middle initial
        first_name = request.POST.get("first_name", "").strip() or request.user.first_name
        last_name = request.POST.get("last_name", "").strip() or request.user.last_name
        middle_initial = request.POST.get("middle_initial", "").strip() or (profile.middle_name or "")

        # Immutable security rule: email cannot be altered by applicant
        email = request.user.email

        # Phone handling: use profile.phone if already present; otherwise require from POST
        if profile.phone and profile.phone.strip():
            phone = profile.phone.strip()
        else:
            phone = request.POST.get("phone", "").strip()
            if not phone:
                return render(request, "jobs/partials/application_error.html", {
                    "error": "Please provide a valid phone number to submit your application."
                })
            profile.phone = phone
            profile.save(update_fields=["phone"])

        # Update user/profile records if name details were modified on the form
        user_updated = False
        if first_name and first_name != request.user.first_name:
            request.user.first_name = first_name
            user_updated = True
        if last_name and last_name != request.user.last_name:
            request.user.last_name = last_name
            user_updated = True
        if user_updated:
            request.user.save(update_fields=["first_name", "last_name"])

        if middle_initial and middle_initial != profile.middle_name:
            profile.middle_name = middle_initial
            profile.save(update_fields=["middle_name"])

        # Create application instance immediately with pending status
        app_id = uuid4().hex[:8].upper()
        application = Application(
            application_id=app_id,
            applicant=request.user,
            job=job,
            first_name=first_name,
            middle_initial=middle_initial,
            last_name=last_name,
            email=email,
            phone=phone,
            status="Screening",
            resume_processed=False,
            ai_score=0,
            ai_recommendation="Pending Review",
            ai_summary="AI screening is currently in progress."
        )

        # Snapshot the resume file specifically for this application
        if profile.default_resume:
            try:
                profile.default_resume.open("rb")
                content = profile.default_resume.read()
                filename = os.path.basename(profile.default_resume.name or "resume.pdf")
                application.resume.save(filename, ContentFile(content), save=False)
            except Exception as resume_copy_err:
                import logging
                logging.getLogger(__name__).warning("Failed to clone resume for application: %s", resume_copy_err)
                application.resume = profile.default_resume
            finally:
                try:
                    profile.default_resume.close()
                except Exception:
                    pass
        try:
            application.save()
        except IntegrityError:
            return render(request, "jobs/partials/application_error.html", {
                "job": job,
                "profile": profile,
                "error": "Duplicate submission detected: You have already applied for this job."
            })

        # Run AI screening and resume text extraction in the background
        # This keeps the submission instant (<100ms) and completely non-blocking for applicants
        thread = threading.Thread(
            target=_async_screen_application,
            args=(application.id, profile.resume_text),
            daemon=True
        )
        thread.start()

        # Send confirmation email to applicant via Gmail API synchronously so serverless runtimes (Vercel) cannot terminate it
        try:
            email_sent = send_application_submitted_email(application, async_send=False)
            if not email_sent:
                import logging
                logging.getLogger(__name__).warning(
                    "Submission confirmation email could not be dispatched to %s for application %s",
                    application.email,
                    application.application_id,
                )
        except Exception as email_err:
            import logging
            logging.getLogger(__name__).error(
                "Unexpected error sending confirmation email to %s: %s",
                application.email,
                email_err,
            )
        
        # Immediately render application success page
        return render(request, "jobs/partials/application_success.html", {
            "application": application,
            "job": job,
        })
        
    except Exception as e:
        return render(request, "jobs/partials/application_error.html", {
            "error": (
                f"An error occurred while processing your application: {str(e)}"
            )
        })

@login_required(login_url="applicant_login")
def upload_resume(request, pk):

    job = get_object_or_404(Job, pk=pk)

    if request.method != "POST":
        return render(request, "jobs/apply.html", {
            "job": job
        })

    # Rate limiting & spam prevention (3 per hour per IP & account)
    is_limited, limit_err = check_rate_limit(
        request,
        action_key="upload_resume",
        limit=3,
        window_seconds=3600,
        account_identifier=request.user.email,
        enable_debounce=True,
        debounce_seconds=3,
    )
    if is_limited:
        return render(request, "jobs/apply.html", {
            "job": job,
            "error": limit_err,
        }, status=429)

    resume = request.FILES.get("resume")

    # Check if a file was uploaded
    if not resume:
        return render(request, "jobs/apply.html", {
            "job": job,
            "error": "Please upload a resume."
        })

    # Allowed resume file types
    allowed_extensions = [".pdf", ".doc", ".docx"]

    if not any(
        resume.name.lower().endswith(ext)
        for ext in allowed_extensions
    ):
        return render(request, "jobs/apply.html", {
            "job": job,
            "error": "Only PDF, DOC, or DOCX files are allowed."
        })

    # Maximum file size: 5 MB
    if resume.size > 5 * 1024 * 1024:
        return render(request, "jobs/apply.html", {
            "job": job,
            "error": "Resume must be smaller than 5 MB."
        })

    # Create the application and save the resume.
    # AI processing is intentionally NOT performed here.
    application = Application.objects.create(
        job=job,
        resume=resume,
        status="Screening",
        first_name="",
        middle_initial="",
        last_name="",
        email="",
        phone="",
    )

    # Immediately proceed to the personal information step.
    return render(
        request,
        "jobs/partials/personal_info.html",
        {
            "job": job,
            "application": application,
        }
    )

def application_success(request, application_id):
    application = get_object_or_404(
        Application.objects.select_related("job"),
        application_id=application_id
    )
    
    return render(request, "jobs/partials/application_success.html", {
        "application": application,
        "job": application.job,
    })