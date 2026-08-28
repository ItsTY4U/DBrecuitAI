from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .ai import extract_resume_text, analyze_resume
from django.urls import reverse
import json
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required

from .models import Job, Application
from accounts.models import ApplicantProfile

def jobs(request):
    try:
        query = request.GET.get("q", "")
        department = request.GET.get("department", "")

        jobs = Job.objects.filter(status="Active")

        if query:
            jobs = jobs.filter(
                Q(title__icontains=query) |
                Q(department__icontains=query)
            )

        if department:
            jobs = jobs.filter(department=department)

        if request.headers.get("HX-Request"):
            return render(
                request,
                "jobs/partials/jobs_list.html",
                {"jobs": jobs},
            )

        return render(
            request,
            "jobs/jobs.html",
            {"jobs": jobs},
        )

    except Exception as e:
        import traceback
        return HttpResponse(
            f"<pre>{traceback.format_exc()}</pre>",
            status=500
        )

def job_detail(request, id):
    job = get_object_or_404(Job, id=id)
    return render(request, "jobs/job_detail.html", {
        "job": job
    })  

@login_required(login_url="applicant_login")
def apply_job(request, pk):
    job = get_object_or_404(Job, pk=pk, status="Active")

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
    # Prevent duplicate applications
    existing_application = Application.objects.filter(
        applicant=request.user,
        job=job
    ).first()
    
    if existing_application:
        return render(request, "jobs/partials/application_error.html", {
            "job": job,
            "profile": profile,
            "error": ("You have already applied for this job.")
        })
        
    try:
        # Create application linked to logged-in applicant
        application = Application.objects.create(
            applicant=request.user,
            job=job,
            first_name=request.user.first_name,
            middle_initial=profile.middle_name,
            last_name=request.user.last_name,
            email=request.user.email,
            phone=profile.phone,
            
            # use the applicant default resume
            resume=profile.default_resume,
            status="Pending"
        )
        # Use the already processed resume text 
        resume_text = profile.resume_text
        
        # Run job-specific AI analysis
        ai = analyze_resume(
            resume_text,
            job
        )
        
        application.ai_score = ai.get("score", 0)
        
        application.ai_summary = ai.get("summary", "")
        
        application.ai_strengths = "\n".join(ai.get("strengths", []))
        
        application.ai_weaknesses = "\n".join(ai.get("weaknesses", []))
        
        application.resume_processed = True
        
        # After AI screening
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

    # Only allow PDF files
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

    try:
        # Extract text from PDF
        resume_text = extract_resume_text(application.resume.path)

        # Analyze using Gemini
        ai = analyze_resume(resume_text, job)

        application.first_name = ai.get("first_name", "")
        application.middle_initial = ai.get("middle_initial", "")
        application.last_name = ai.get("last_name", "")
        application.email = ai.get("email", "")
        application.phone = ai.get("phone", "")

        application.ai_score = ai.get("score", 0)
        application.ai_summary = ai.get("summary", "")

        application.ai_strengths = "\n".join(
            ai.get("strengths", [])
        )

        application.ai_weaknesses = "\n".join(
            ai.get("weaknesses", [])
        )

        application.resume_processed = True
        application.save()

    except Exception as e:
        # Delete the incomplete application
        application.delete()

        return render(request, "jobs/apply.html", {
            "job": job,
            "error": str(e)
        })

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
        Application,
        application_id=application_id
    )
    
    return render(request,"jobs/partials/application_success.html",{
        "application":application
    })