from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Job

def jobs(request):
    query = request.GET.get("q", "")

    jobs = Job.objects.filter(is_active=True)

    if query:
        jobs = jobs.filter(title__icontains=query)

    # If the request came from HTMX, only return the job list
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