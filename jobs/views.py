from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Job, Application
from .ai import extract_resume_text, analyze_resume

def jobs(request):
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
        return render(request, "jobs/partials/jobs_list.html", {
            "jobs": jobs
        })
    return render(request, "jobs/jobs.html", {
        "jobs": jobs
    })

def job_detail(request, id):
    job = get_object_or_404(Job, id=id)
    return render(request, "jobs/job_detail.html", {
        "job": job
    })
    
def apply_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    
    if request.method == "POST":
        application = get_object_or_404(
            Application,
            pk=request.POST.get("application_id"),
        )
        application.first_name = request.POST.get("first_name")
        application.middle_initial = request.POST.get("middle_initial")
        application.last_name = request.POST.get("last_name")
        application.email = request.POST.get("email")
        application.phone = request.POST.get("phone")
        application.status = "Pending"
        application.save()
        
        return render(request, "jobs/partials/success.html", {"application":application})
    
    return render(request, "jobs/apply.html", {"job": job})

def upload_resume(request, pk):
    job = get_object_or_404(Job, pk=pk)
    
    if request.method == "POST":
        resume = request.FILES.get("resume")
        
        application = Application.objects.create(
            job=job,
            resume=resume,
            status="Draft",
            
            #tempo placeholder
            first_name="",
            middle_initial="",
            last_name="",
            email="",
            phone="",
        )
        resume_text = extract_resume_text(application.resume.path)

        ai = analyze_resume(resume_text, job)

        application.first_name = ai["first_name"]
        application.middle_initial = ai["middle_initial"]
        application.last_name = ai["last_name"]
        application.email = ai["email"]
        application.phone = ai["phone"]

        application.ai_score = ai["score"]
        application.ai_summary = ai["summary"]
        application.ai_strengths = ai["strengths"]
        application.ai_weaknesses = ai["weaknesses"]

        application.resume_processed = True
        application.save()

        return render(request, "jobs/partials/personal_info.html",{
            "job": job, "application": application,
        })