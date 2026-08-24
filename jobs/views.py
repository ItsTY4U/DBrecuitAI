from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Job, Application
from django.urls import reverse
import json

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
        Application,
        application_id=application_id
    )
    
    return render(request, "jobs/partials/application_success.html", {
        "application": application
    })