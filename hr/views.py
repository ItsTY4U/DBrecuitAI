from django.shortcuts import render, redirect, get_object_or_404
from jobs.models import Application, Job, Requirement
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required

# Create your views here.
def hr_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        
        print("Username:", username)
        print("Email:", email)
        print("Password:", password)
        
        user = authenticate(request, username=username, email=email, password=password)
        
        print("User:", user)
        
        if user is not None and user.is_staff:
            login(request, user)
            print("Logged in")
            return redirect("dashboard")
        
        messages.error(request, "Invalid username or password.")
        
    return render(request, "hr/login.html")


@staff_member_required
def dashboard(request):
    total_applications = Application.objects.count()
    screening = Application.objects.filter(status="Screening").count()
    hired = Application.objects.filter(status="Hired").count()
    active_jobs = Job.objects.filter(is_active=True).count()
    interview = Application.objects.filter(status="Interview").count()
    #qualified = Application.objects.filter(status="Qualified").count()
    pending_count = Application.objects.filter(status="pending").count()
    interview_count = Application.objects.filter(status="Interview").count()
    
    recent_applications = (
        Application.objects.select_related("job").order_by("-created_at")[:5]
    )
    
    content = {
        "total_applications": total_applications,
        "screening": screening,
        "hired": hired,
        "active_jobs":active_jobs,
        "recent_applications":recent_applications,
        "pending_count": pending_count,
        "interview_count": interview_count,
    }
    return render(request, "hr/dashboard.html", content)

@staff_member_required
def create_job(request):
    if request.method == "POST":
        job = Job.objects.create(
            title=request.POST.get("title"),
            department=request.POST.get("department"),
            job_type=request.POST.get("job_type"),
            description=request.POST.get("description"),
            is_active=True,
        )
        requirements = request.POST.getlist("requirements")

        for req in requirements:
            if req.strip():
                Requirement.objects.create(
                    job=job,
                    text=req.strip()
                )
    return redirect("job_management")


def job_management(request):
    jobs = Job.objects.filter(is_active=True)
    
    return render(request, "hr/job_management.html", {
        "jobs": jobs,
    })
    

def manage_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == "POST":
        job.title = request.POST["title"]
        job.department = request.POST["department"]
        job.job_type = request.POST["job_type"]
        job.description = request.POST["description"]
        job.is_active = request.POST["is_active"] == "True"
        
        job.save()
        return redirect("job_management")
    return render(request, "hr/manage_job.html",{
        "job":job,
    })