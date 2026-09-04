from django.shortcuts import render, redirect, get_object_or_404
from jobs.models import Application, Job, Requirement
from .models import Interview
from django.db.models import Q, Count, Prefetch
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from datetime import date, timedelta
from django.utils import timezone
from django.core.paginator import Paginator

from django.contrib.auth import logout
from django.shortcuts import redirect

from django.views.decorators.cache import never_cache

# Create your views here.
def hr_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        
        user = authenticate(request, username=username, email=email, password=password)
                
        if user is not None and user.is_staff:
            login(request, user)
            return redirect("dashboard")
        
        messages.error(request, "Invalid username or password.")
        
    return render(request, "hr/login.html")

def hr_logout(request):
    logout(request)
    return redirect("hr_login")

@never_cache
@staff_member_required
def dashboard(request):
    total_applications = Application.objects.count()
    screening = Application.objects.filter(status="Screening").count()
    hired = Application.objects.filter(status="Hired").count()
    active_jobs = Job.objects.filter(status="Active").count()
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

@never_cache
@staff_member_required
def create_job(request):
    if request.method == "POST":
        job = Job.objects.create(
            title=request.POST.get("title"),
            department=request.POST.get("department"),
            job_type=request.POST.get("job_type"),
            description=request.POST.get("description"),
            status="Active",
        )
        requirements = request.POST.getlist("requirements")

        for req in requirements:
            if req.strip():
                Requirement.objects.create(
                    job=job,
                    text=req.strip()
                )
    return redirect("job_management")

@never_cache
@staff_member_required
def job_management(request):
    active_jobs = (
        Job.objects.filter(status="Active")
        .annotate(applicant_count=Count("application", distinct=True))
        .prefetch_related("requirements_list")
        .order_by("-posted_date")
    )
    
    inactive_jobs = (
        Job.objects.filter(status="Inactive")
        .annotate(applicant_count=Count("application", distinct=True))
        .prefetch_related("requirements_list")
        .order_by("-posted_date")
    )
    
    total_active = active_jobs.count()
    total_inactive = inactive_jobs.count()
    total_jobs = total_active + total_inactive
    
    return render(request, "hr/job_management.html", {
        "active_jobs": active_jobs,
        "inactive_jobs": inactive_jobs,
        "total_active": total_active,
        "total_inactive": total_inactive,
        "total_jobs": total_jobs,
    })

@never_cache    
@staff_member_required
def manage_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == "POST":
        job.title = request.POST.get("title", job.title)
        job.department = request.POST.get("department", job.department)
        job.job_type = request.POST.get("job_type", job.job_type)
        job.description = request.POST.get("description", job.description)
        job.status = request.POST.get("status", job.status)
        job.save()
        
        # Handle requirements update
        requirements = request.POST.getlist("requirements")
        if requirements:
            job.requirements_list.all().delete()
            for req in requirements:
                if req.strip():
                    Requirement.objects.create(job=job, text=req.strip())
                    
        return redirect("job_management")
        
    requirements = job.requirements_list.all()
    applicant_count = Application.objects.filter(job=job).count()
    
    return render(request, "hr/manage_job.html", {
        "job": job,
        "requirements": requirements,
        "applicant_count": applicant_count,
    })
    
import ast

def parse_ai_bullets(text):
    if not text:
        return []
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            items = ast.literal_eval(text)
            if isinstance(items, list):
                return [str(i).strip() for i in items if i and str(i).strip()]
        except Exception:
            pass
    lines = [line.strip().lstrip("-*• ") for line in text.split("\n") if line.strip()]
    return lines

@never_cache
@staff_member_required
def candidates(request):
    total_candidates = Application.objects.count()
    screening_count = Application.objects.filter(status="Screening").count()
    interview_count = Application.objects.filter(status="Interview").count()
    hired_count = Application.objects.filter(status="Hired").count()

    departments = (
        Job.objects.filter(status="Active")
        .values("department")
        .annotate(job_count=Count("id"))
        .order_by("department")
    )

    department_cards = []

    for dept in departments:
        dept_apps = Application.objects.filter(
            job__department=dept["department"],
            job__status="Active"
        )
        total_dept_applicants = dept_apps.count()
        top_applicants = (
            dept_apps.select_related("job")
            .order_by("-ai_score")[:3]
        )

        department_cards.append({
            "department": dept["department"],
            "job_count": dept["job_count"],
            "total_applicants": total_dept_applicants,
            "top_applicants": top_applicants,
        })

    return render(request, "hr/candidates.html", {
        "department_cards": department_cards,
        "total_candidates": total_candidates,
        "screening_count": screening_count,
        "interview_count": interview_count,
        "hired_count": hired_count,
    })

@never_cache
@staff_member_required
def candidate_department(request, department):
    # Shared filters from query params
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "")
    ITEMS_PER_PAGE = 15

    active_jobs = Job.objects.filter(department=department, status="Active").order_by("title")

    total_candidates = Application.objects.filter(
        job__department=department,
        job__status="Active"
    ).count()

    role_data = []
    for job in active_jobs:
        qs = Application.objects.filter(job=job)

        # Apply search filter
        if search_query:
            qs = qs.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(application_id__icontains=search_query)
            )

        # Apply status filter
        if status_filter:
            qs = qs.filter(status=status_filter)

        qs = qs.order_by("-ai_score", "-created_at")

        # Per-role pagination key: page_<job_id>
        page_key = f"page_{job.pk}"
        page_number = request.GET.get(page_key, 1)
        paginator = Paginator(qs, ITEMS_PER_PAGE)
        page_obj = paginator.get_page(page_number)

        role_data.append({
            "job": job,
            "page_obj": page_obj,
            "page_key": page_key,
            "total_count": qs.count(),
        })

    # Build a query string that preserves search/status but drops page_* keys
    filter_params = {}
    if search_query:
        filter_params["search"] = search_query
    if status_filter:
        filter_params["status"] = status_filter

    return render(
        request,
        "hr/candidate_department.html",
        {
            "department": department,
            "role_data": role_data,
            "total_candidates": total_candidates,
            "search_query": search_query,
            "status_filter": status_filter,
            "filter_params": filter_params,
            "status_choices": ["Pending", "Screening", "Interview", "Hired", "Rejected"],
        }
    )

@never_cache
@staff_member_required
def candidate_detail(request, pk):
    application = get_object_or_404(
        Application.objects.select_related("job"),
        pk=pk
    )
    
    strengths = parse_ai_bullets(application.ai_strengths)
    weaknesses = parse_ai_bullets(application.ai_weaknesses)
    
    return render(request, "hr/candidate_detail.html", {
        "application": application,
        "strengths": strengths,
        "weaknesses": weaknesses,
    })

@never_cache
@staff_member_required
def update_application_status(request, pk):
    application = get_object_or_404(Application, pk=pk)
    
    if request.method == "POST":
        application.status = request.POST.get("status")
        application.save()
        
    return redirect(request.META.get("HTTP_REFERER", "candidates"))

@never_cache
@staff_member_required
def interviews(request):
    
    total = Interview.objects.count()
    
    scheduled = Interview.objects.filter(status="Scheduled").count()
    
    ongoing = Interview.objects.filter(status="Ongoing").count()
    
    completed = Interview.objects.filter(status="Completed").count()
    
    cancelled = Interview.objects.filter(status="Cancelled").count()
    
    today = timezone.localdate()
    three_days = today + timedelta(days=3)

    todays_schedule = (
        Interview.objects.filter(date=today)
        .prefetch_related("applicants__job")
        .order_by("time")
    )
    
    upcoming_interviews = (
        Interview.objects.filter(
            date__gt=today,
            date__lte=three_days
        )
        .prefetch_related("applicants__job")
        .order_by("date", "time")
    )
    
    overdue_interviews = (
        Interview.objects.filter(date__lt=today)
        .exclude(status__in=["Completed", "Cancelled"])
        .prefetch_related("applicants__job")
        .order_by("date", "time")
    )
    
    jobs = ( Job.objects.filter(status="Active").prefetch_related(
        Prefetch("application",
            queryset=Application.objects.filter(status="Interview",
                                    interview__isnull=True)
                                    .order_by("-ai_score")
            )
        )
    )
    
    job_interviews = []

    for job in Job.objects.filter(status="Active"):

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
        
        "jobs": jobs,
        "job_interviews": job_interviews,
        "today": today,
        
        "todays_schedule":todays_schedule,
        "upcoming_interviews": upcoming_interviews,
        "overdue_interviews": overdue_interviews,    
        }
    
    return render(request, "hr/interview.html", context,)

@never_cache
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

    
@never_cache
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

@never_cache    
@staff_member_required
def update_interview_status(request, pk):

    interview = get_object_or_404(
        Interview,
        pk=pk
    )

    if request.method == "POST":

        status = request.POST.get("status")

        interview.status = status

        # If rescheduled, update date and time
        if status == "Rescheduled":

            new_date = request.POST.get("date")
            new_time = request.POST.get("time")

            if new_date:
                interview.date = new_date

            if new_time:
                interview.time = new_time

        interview.save()

    return redirect(
        "interview_detail",
        pk=interview.id
    )