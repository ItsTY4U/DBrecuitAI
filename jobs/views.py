from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Job, Application
from .ai import extract_resume_text, analyze_resume

def jobs(request):
    try:
        query = request.GET.get("q", "")
        department = request.GET.get("department", "")

        jobs = Job.objects.filter(is_active=True)

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
    
def apply_job(request, pk):
    job = get_object_or_404(Job, pk=pk)

    if request.method == "POST":

        application_id = request.POST.get("application_id")

        if not application_id:
            return render(request, "jobs/apply.html", {
                "job": job,
                "error": "Application ID is missing."
            })

        application = get_object_or_404(
            Application,
            application_id=application_id,
        )

        application.first_name = request.POST.get("first_name")
        application.middle_initial = request.POST.get("middle_initial")
        application.last_name = request.POST.get("last_name")
        application.email = request.POST.get("email")
        application.phone = request.POST.get("phone")
        application.status = "Pending"

        application.save()

        return render(
            request,
            "jobs/partials/success.html",
            {
                "application": application
            }
        )

    return render(
        request,
        "jobs/apply.html",
        {
            "job": job
        }
    )

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
    if not resume.name.lower().endswith(".pdf"):
        return render(request, "jobs/apply.html", {
            "job": job,
            "error": "Only PDF files are allowed."
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
        status="Draft",
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