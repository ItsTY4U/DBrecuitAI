from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Job, Application
from .ai import extract_resume_text, analyze_resume
from django.urls import reverse
import json
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required

from .models import Job, Application
from accounts.models import ApplicantProfile

def jobs(request):
    try:
        query = request.GET.get("q", "").strip()
        department = request.GET.get("department", "").strip()

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

        # Fast partial response for HTMX search / filter requests
        if request.headers.get("HX-Request"):
            return render(
                request,
                "jobs/partials/jobs_list.html",
                {"jobs": jobs_qs},
            )

        return render(
            request,
            "jobs/jobs.html",
            {"jobs": jobs_qs},
        )

    except Exception as e:
        import traceback
        return HttpResponse(
            f"<pre>{traceback.format_exc()}</pre>",
            status=500
        )
        
def job_detail(request, id):
    job = get_object_or_404(
        Job.objects.prefetch_related("requirements_list"),
        id=id
    )
    return render(request, "jobs/job_detail.html", {
        "job": job
    }) 

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
    
    # Applicant must have a resume
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
        
    # Resume must be processed
    if not profile.resume_processed or not profile.resume_text:
        return render(request, "jobs/partials/application_error.html", {
            "error": ("Your resume has not been processed yet. "
                    "Please update and process your resume from your profile")
        })
        
    # GET request
    if request.method == "GET":
        return render(request, "jobs/apply.html", {
            "job": job,
            "profile": profile,
        })
        
    # POST request
    # Prevent duplicate applications (fast query using index)
    existing_application = Application.objects.filter(
        applicant=request.user,
        job=job
    ).only("id").first()
    
    if existing_application:
        return render(request, "jobs/partials/application_error.html", {
            "job": job,
            "profile": profile,
            "error": ("You have already applied for this job.")
        })
        
    try:
        # Attempt AI analysis with safe fallback if Gemini rate limits or times out
        ai = {}
        try:
            resume_text = profile.resume_text
            if resume_text:
                ai = analyze_resume(resume_text, job)
        except Exception as ai_err:
            import logging
            logging.getLogger(__name__).warning("Gemini resume analysis fallback triggered: %s", ai_err)
            ai = {
                "score": 0,
                "summary": "AI evaluation queued.",
                "strengths": [],
                "weaknesses": [],
            }
        
        # Create complete application in a single INSERT
        application = Application.objects.create(
            applicant=request.user,
            job=job,
            first_name=request.user.first_name,
            middle_initial=profile.middle_name,
            last_name=request.user.last_name,
            email=request.user.email,
            phone=profile.phone,
            resume=profile.default_resume,
            status="Pending",
            ai_score=ai.get("score", 0),
            ai_summary=ai.get("summary", ""),
            ai_strengths="\n".join(ai.get("strengths", [])),
            ai_weaknesses="\n".join(ai.get("weaknesses", [])),
            resume_processed=True,
        )
        
        return render(request, "jobs/partials/application_success.html",
                    {
                        "application": application,
                        "job": job,
                    })
        
    except Exception as e:
        return render(request, "jobs/partials/application_error.html",
                    {
                        "error": (
                            f"An error occured while processing your application: {str(e)}"
                        )
                    })

@login_required(login_url="applicant_login")
def upload_resume(request, pk):

    job = get_object_or_404(Job, pk=pk)

    if request.method != "POST":
        return render(request, "jobs/apply.html", {
            "job": job
        })

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
        status="Pending",
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