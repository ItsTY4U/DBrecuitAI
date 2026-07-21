from django.shortcuts import render, redirect, get_object_or_404
from jobs.models import Application, Job, Requirement
from .models import Interview
from django.db.models import Q, Count, Prefetch
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from datetime import date, timedelta

# Create your views here.
def hr_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        
        
        user = authenticate(request, username=username, email=email, password=password)
                
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
    pending_count = Application.objects.filter(status="Pending").count()
    interview_count = Application.objects.filter(status="Interview").count()
    
    if total_applications > 0:
        screening_percent = screening / total_applications * 100
        interview_percent = interview / total_applications * 100
        hired_percent = hired / total_applications * 100
    else:
        screening_percent = 0
        interview_percent = 0
        hired_percent = 0
    
    recent_applications = (
        Application.objects.select_related("job").order_by("-created_at")[:5]
    )
    
    content = {
        "total_applications": total_applications,
        "screening": screening,
        "hired": hired,
        "interview": interview,
        "active_jobs":active_jobs,
        "recent_applications":recent_applications,
        "pending_count": pending_count,
        "interview_count": interview_count,
        "screening_percent": screening_percent,
        "interview_percent": interview_percent,
        "hired_percent": hired_percent,
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

@staff_member_required
def job_management(request):
    jobs = Job.objects.filter(is_active=True)
    
    return render(request, "hr/job_management.html", {
        "jobs": jobs,
    })
    
@staff_member_required
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
    
@staff_member_required
def candidates(request):
    departments = (
        Job.objects.filter(is_active=True)
        .values("department")
        .annotate(job_count=Count("id"))
        .order_by("department")
    )

    department_cards = []

    for dept in departments:
        top_applicants = (
            Application.objects.filter(
                job__department=dept["department"],
                job__is_active=True
            )
            .select_related("job")
            .order_by("-ai_score")[:3]
        )

        department_cards.append({
            "department": dept["department"],
            "job_count": dept["job_count"],
            "top_applicants": top_applicants,
        })

    return render(request, "hr/candidates.html", {
        "department_cards": department_cards,
    })

@staff_member_required
def candidate_department(request, department):
    jobs = Job.objects.filter(
        department=department,
        is_active=True
    ).prefetch_related("application")

    return render(
        request,
        "hr/candidate_department.html",
        {
            "department": department,
            "jobs": jobs,
        }
    )

@staff_member_required
def candidate_detail(request, pk):
    application = get_object_or_404(
        Application.objects.select_related("job"),
        pk=pk
    )
    
    return render(request, "hr/candidate_detail.html", {"application": application,})

@staff_member_required
def update_application_status(request, pk):
    application = get_object_or_404(Application, pk=pk)
    
    if request.method == "POST":
        application.status = request.POST.get("status")
        application.save()
        
    return redirect(request.META.get("HTTP_REFERER", "candidates"))

@staff_member_required
def interviews(request):
    
    total = Interview.objects.count()
    
    scheduled = Interview.objects.filter(status="Scheduled").count()
    
    ongoing = Interview.objects.filter(status="Ongoing").count()
    
    completed = Interview.objects.filter(status="Completed").count()
    
    cancelled = Interview.objects.filter(status="Cancelled").count()
    
    today = date.today()
    three_days = today + timedelta(days=3)
    
    upcoming_interviews = (
        Interview.objects.filter(
            date__range=[today, three_days]
        )
        .prefetch_related("applicants")
        .order_by("date", "time")
    )
    
    jobs = ( Job.objects.filter(is_active=True).prefetch_related(
        Prefetch("application",
            queryset=Application.objects.filter(status="Interview",
                                    interview__isnull=True)
                                    .order_by("-ai_score")
            )
        )
    )
    
    job_interviews = []

    for job in Job.objects.filter(is_active=True):

        waiting = Application.objects.filter(
            job=job,
            status="Interview",
            interview__isnull=True,
        ).count()

        interviews = Interview.objects.filter(
            applicants__job=job
        ).distinct().order_by("date", "time")

        # Hide only jobs that have neither waiting applicants nor interviews
        if waiting == 0 and not interviews.exists():
            continue

        job_interviews.append({
            "job": job,
            "waiting": waiting,
            "interviews": interviews,
        })
        
    context = {
        "total": total,
        "scheduled": scheduled,
        "ongoing": ongoing,
        "completed": completed,
        "cancelled": cancelled,
        "upcoming_interviews": upcoming_interviews,
        "jobs": jobs,
        "job_interviews": job_interviews,
        "today": today,
    }
    
    return render(request, "hr/interview.html", context,)

@staff_member_required
def schedule_interview(request, job_id):
    
    job = get_object_or_404(Job, pk=job_id)
    
    applicants = Application.objects.filter(
        job=job,
        status="Interview",
        interview__isnull=True, 
    ).order_by("-ai_score")
    
    
    if request.method == "POST":
        interview = Interview.objects.create(
            interview_type=request.POST["interview_type"],
            interviewer=request.POST["interviewer"],
            date=request.POST["date"],
            time=request.POST["time"],
            location=request.POST["location"],
            notes=request.POST["notes"],
        )
        
        ids = request.POST.getlist("applicants")
        
        interview.applicants.set(ids)
        
        return redirect("interviews")
    
    return render(
        request, "hr/schedule_interview.html", {
            "job": job,
            "applicants": applicants,
            "interview": Interview,
            }
    )
    
@staff_member_required
def interview_detail(request, pk):
    interview = get_object_or_404(
        Interview.objects.prefetch_related(
            "applicants__job"
        ), pk=pk
    )
    
    return render(
        request, "hr/interview_detail.html",{"interview": interview,}
    )
    
@staff_member_required
def update_interview_status(request, pk):
    interview = get_object_or_404(Interview, pk=pk)
        
    if request.method == "POST":
        interview.status = request.POST["status"]
        interview.save()
            
    return redirect("interview_detail", pk=pk)