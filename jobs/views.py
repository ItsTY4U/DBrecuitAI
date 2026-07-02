from django.shortcuts import render, get_object_or_404
from .models import Job
# Create your views here.
def jobs(request):
    jobs = Job.objects.filter(is_active=True)
    
    return render(request, "jobs/jobs.html", {
        "jobs": jobs
    })
    
def job_detail(request, id):
    job = get_object_or_404(Job, id=id)
    
    return render(request, "jobs/job_detail.html", {
        "job":job
    })