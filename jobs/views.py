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
from .models import Job, Application
from accounts.models import ApplicantProfile

def jobs(request):
    try:
        query = request.GET.get("q", "").strip()
        department = request.GET.get("department", "").strip()

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

        # Fast partial response for HTMX search / filter requests
        if request.headers.get("HX-Request"):
            return render(
                request,
                "jobs/partials/jobs_list.html",
                {"jobs": jobs_list},
            )

        return render(
            request,
            "jobs/jobs.html",
            {"jobs": jobs_list},
        )

    except Exception as e:
        import traceback
        return HttpResponse(
            f"<pre>{traceback.format_exc()}</pre>",
            status=500
        )
        
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
                "recommendation": "Pending Review",
                "match_level": "Unsatisfactory",
                "summary": "AI evaluation queued.",
                "matched_qualifications": [],
                "missing_qualifications": ["Evaluation queued for manual review."],
                "strengths": [],
                "weaknesses": ["Automated evaluation temporarily unavailable."],
                "skills_match": 0,
                "experience_match": 0,
                "education_match": 0,
                "qualification_match": 0,
                "criteria_weights": {},
                "weight_reasoning": {},
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
            status="Pending"
        )

        # ==============================
        # AI OVERALL RESULTS
        # ==============================

        application.ai_score = ai.get("score", 0)

        application.ai_match_level = ai.get(
            "match_level",
            ""
        )

        application.ai_recommendation = ai.get(
            "recommendation",
            ""
        )


        # ==============================
        # AI SUMMARY
        # ==============================

        application.ai_summary = ai.get(
            "summary",
            ""
        )


        # ==============================
        # AI STRENGTHS / WEAKNESSES
        # ==============================

        application.ai_strengths = "\n".join(
            ai.get("strengths", [])
        )

        application.ai_weaknesses = "\n".join(
            ai.get("weaknesses", [])
        )


        # ==============================
        # QUALIFICATION ANALYSIS
        # ==============================

        application.ai_matched_qualifications = "\n".join(
            ai.get("matched_qualifications", [])
        )

        application.ai_missing_qualifications = "\n".join(
            ai.get("missing_qualifications", [])
        )


        # ==============================
        # AI COMPONENT SCORES
        # ==============================

        application.ai_skills_match = ai.get(
            "skills_match",
            0
        )

        application.ai_experience_match = ai.get(
            "experience_match",
            0
        )

        application.ai_education_match = ai.get(
            "education_match",
            0
        )

        application.ai_qualification_match = ai.get(
            "qualification_match",
            0
        )
        
        # application.ai_recommendation = data.get("recommendation", "")
        application.ai_criteria_weights = ai.get("criteria_weights", {})
        application.ai_weight_reasoning = ai.get("weight_reasoning", {})


        # ==============================
        # APPLICATION STATUS
        # ==============================

        application.resume_processed = True

        application.status = "Pending"

        application.save()
        
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