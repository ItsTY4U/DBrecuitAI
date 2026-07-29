from email.mime import application

from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Job, Application
from .ai import extract_resume_text, analyze_resume
from django.urls import reverse
import json

from jobs import ai

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

def apply_job(request, pk):
    job = get_object_or_404(Job, pk=pk)

    if request.method == "POST":
        application_id = request.POST.get("application_id")

        if not application_id:
            return HttpResponse("Application ID is missing.", status=400)

        application = get_object_or_404(
            Application,
            application_id=application_id,
            job=job
        )

        application.first_name = request.POST.get("first_name", "")
        application.middle_initial = request.POST.get("middle_initial", "")
        application.last_name = request.POST.get("last_name", "")
        application.email = request.POST.get("email", "")
        application.phone = request.POST.get("phone", "")
        application.status = "Pending"
        application.save()

        # ← Just render the partial directly, no redirect needed
        return render(request, "jobs/partials/application_success.html", {
            "application": application,
            "job": job,
        })

    return render(request, "jobs/apply.html", {"job": job})

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
        print("===== STEP 1: Opening resume =====")

    # Extract text from PDF
        with application.resume.open("rb") as resume_file:
            print("===== STEP 2: Resume opened =====")

            resume_text = extract_resume_text(resume_file)

            print("===== STEP 3: Resume text extracted =====")
            print(f"Resume length: {len(resume_text)}")

        print("===== STEP 4: Calling Gemini =====")

        # Analyze using Gemini
        ai = analyze_resume(resume_text, job)

        print("========== AI RESPONSE ==========")
        print(ai)

        print("PHONE VALUE:")
        print(repr(ai.get("phone")))

        print("PHONE LENGTH:")
        print(len(str(ai.get("phone", ""))))

        print("===== STEP 5: Gemini finished =====")

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

        print("===== STEP 6: Application saved =====")

    except Exception as e:
        import traceback

        print("===== ERROR =====")
        traceback.print_exc()

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