from django.shortcuts import render, redirect, get_object_or_404
from jobs.models import Application, Job, Requirement
from .models import Interview
from django.db.models import Q, Count, Prefetch
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from datetime import date, timedelta
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from functools import wraps
from django.core.paginator import Paginator

from django.views.decorators.cache import never_cache

from collections import defaultdict

# Create your views here.
def hr_required(view_func=None, login_url="hr_login"):
    """
    Decorator for views that checks that the user is logged in, is staff,
    is not superuser, and belongs to the 'HR' group.
    - If user is not authenticated: redirects to `login_url` with ?next=...
    - If user is authenticated and HR: grants access.
    - Otherwise: raises PermissionDenied (403).
    Supports both @hr_required and @hr_required(login_url="...").
    """
    if isinstance(view_func, str):
        actual_login_url = view_func
        actual_view_func = None
    else:
        actual_login_url = login_url
        actual_view_func = view_func

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path(), actual_login_url)

            if user.is_staff and not user.is_superuser and user.groups.filter(name="HR").exists():
                return view(request, *args, **kwargs)

            raise PermissionDenied
        return wrapper

    if callable(actual_view_func):
        return decorator(actual_view_func)
    return decorator


@never_cache
def hr_login(request):
    
    if request.user.is_authenticated:
        if request.user.groups.filter(name="HR").exists():
            return redirect("dashboard")
        
        if request.user.is_superuser:
            return redirect("/superadmin/")
        
        return redirect("home")
    
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        
        
        user = authenticate(request, username=username, password=password)
                
        if user is not None:
            is_hr = (
                user.is_staff 
                and not user.is_superuser
                and user.groups.filter(name="HR").exists()
            )
            
            if is_hr:
                login(request, user)
                return redirect("dashboard")
        
        messages.error(request, "Invalid username or password.")
        
    return render(request, "hr/login.html") 

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
@hr_required
def hr_logout(request):
    logout(request)
    return redirect("hr_login")


@hr_required(login_url="hr_login")
def dashboard(request):
    # 1. Single conditional aggregation query for all application counts
    app_counts = Application.objects.aggregate(
        total=Count("id"),
        screening=Count("id", filter=Q(status="Screening")),
        hired=Count("id", filter=Q(status="Hired")),
        interview=Count("id", filter=Q(status="Interview")),
        pending=Count("id", filter=Q(status="Pending")),
    )

    total_applications = app_counts["total"]
    screening = app_counts["screening"]
    hired = app_counts["hired"]
    interview = app_counts["interview"]
    pending_count = app_counts["pending"]
    interview_count = app_counts["interview"]

    active_jobs = Job.objects.filter(status="Active").count()
    
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
@hr_required(login_url="hr_login")
def create_job(request):
    if request.method == "POST":
        job = Job.objects.create(
            title=request.POST.get("title"),
            department=request.POST.get("department"),
            job_type=request.POST.get("job_type"),
            description=request.POST.get("description"),
            requirements=request.POST.get("requirements", ""),
            status="Active",
        )
        key_qualifications = request.POST.getlist("key_qualification")

        for qualification in key_qualifications:
            if qualification.strip():
                Requirement.objects.create(
                    job=job,
                    text=req.strip()
                )
    return redirect("job_management")

@never_cache
@hr_required(login_url="hr_login")
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
@hr_required(login_url="hr_login")
def manage_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == "POST":
        job.title = request.POST["title"]
        job.department = request.POST["department"]
        job.job_type = request.POST["job_type"]
        job.description = request.POST["description"]
        job.status = request.POST.get("status", job.status)
        job.save()
        
        key_qualifications = request.POST.getlist(
            "key_qualifications"
        )
        
        job.requirements_list.all().delete()
        
        for qualification in key_qualifications:
            if qualification.strip():
                Requirement.objects.create(job=job, text=qualification.strip())
                
        return redirect("job_management")
        
    # requirements = job.requirements_list.all()
    # applicant_count = Application.objects.filter(job=job).count()
    
    return render(request, "hr/manage_job.html", {
        "job": job,
    })
    
import ast

@never_cache
@hr_required(login_url="hr_login")
def candidates(request):
    # Single aggregate query for all candidate status counts
    counts = Application.objects.aggregate(
        total=Count("id"),
        screening=Count("id", filter=Q(status="Screening")),
        interview=Count("id", filter=Q(status="Interview")),
        hired=Count("id", filter=Q(status="Hired")),
    )

    departments = (
        Job.objects
        .filter(
            status="Active"
        )
        .exclude(
            department__isnull=True
        )
        .exclude(
            department=""
        )
        .values("department")
        .annotate(job_count=Count("id"))
        .order_by("department")
    )
    dept_applicant_counts = {
        item["job__department"]: item["total"]
        for item in (
            Application.objects.filter(job__status="Active")
            .values("job__department")
            .annotate(total=Count("id"))
        )
    }

    department_cards = []

    for dept in departments:
        dept_name = dept["department"]
        # Look up applicant count in memory (O(1)) instead of querying database per department
        total_dept_applicants = dept_applicant_counts.get(dept_name, 0)

        top_applicants = (
            Application.objects.filter(
                job__department=dept_name,
                job__status="Active"
            )
            .select_related("job")
            .order_by("-ai_score")[:3]
        )

        department_cards.append({
            "department": dept_name,
            "job_count": dept["job_count"],
            "total_applicants": total_dept_applicants,
            "top_applicants": top_applicants,
        })

    return render(request, "hr/candidates.html", 
        {
            "department_cards": department_cards,
            "total_candidates": counts["total"],
            "screening_count": counts["screening"],
            "interview_count": counts["interview"],
            "hired_count": counts["hired"],
        },
    )

@never_cache
@hr_required(login_url="hr_login")
@hr_required
def candidate_department(request, department):
    # Shared filters from query params
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "")
    ITEMS_PER_PAGE = 15

    # Get active jobs under this department
    active_jobs = (
        Job.objects
        .filter(
            department__iexact=department,
            status="Active"
        )
        .order_by("title")
    )

    # Total candidates across the department
    total_candidates = Application.objects.filter(
        job__department__iexact=department,
        job__status="Active"
    ).count()

    role_data = []

    for job in active_jobs:

        # Candidates for this specific job
        qs = Application.objects.filter(
            job=job
        ).select_related("job")

        # Search filter
        if search_query:
            qs = qs.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(application_id__icontains=search_query)
            )

        # Status filter
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Highest AI score first
        qs = qs.order_by(
            "-ai_score",
            "-created_at"
        )

        # Each job gets its own pagination
        page_key = f"page_{job.pk}"
        page_number = request.GET.get(page_key, 1)

        paginator = Paginator(
            qs,
            ITEMS_PER_PAGE
        )

        page_obj = paginator.get_page(page_number)

        role_data.append({
            "job": job,
            "page_obj": page_obj,
            "page_key": page_key,
            "total_count": paginator.count,
        })

    # Preserve filters when changing pages
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
            "status_choices": [
                "Pending",
                "Screening",
                "Interview",
                "Hired",
                "Rejected",
            ],
        },
    )

@never_cache
@hr_required(login_url="hr_login")
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


    return render(request, "hr/candidate_detail.html", 
                {
                    "application": application,
                    "matched_qualifications": application.ai_matched_qualifications.splitlines(),
                    "missing_qualifications": application.ai_missing_qualifications.splitlines(),
                    "strengths": application.ai_strengths.splitlines(),
                    "weaknesses": application.ai_weaknesses.splitlines(),
                    })

@never_cache
@hr_required
def update_application_status(request, pk):
    application = get_object_or_404(Application, pk=pk)
    
    if request.method == "POST":
        application.status = request.POST.get("status")
        application.save()
        
    return redirect(request.META.get("HTTP_REFERER", "candidates"))

@never_cache
@hr_required(login_url="hr_login")
def interviews(request):
    # 1. Combine 5 separate COUNT queries into 1 single aggregate query
    counts = Interview.objects.aggregate(
        total=Count("id"),
        scheduled=Count("id", filter=Q(status="Scheduled")),
        ongoing=Count("id", filter=Q(status="Ongoing")),
        completed=Count("id", filter=Q(status="Completed")),
        cancelled=Count("id", filter=Q(status="Cancelled")),
    )

    today = timezone.localdate()
    three_days = today + timedelta(days=3)

    # 2. Schedule queries
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

    # 3. Prefetch waiting applicants into `waiting_applicants` attribute on each job
    jobs = Job.objects.filter(status="Active").prefetch_related(
        Prefetch(
            "application",
            queryset=Application.objects.filter(
                status="Interview",
                interview__isnull=True
            ).order_by("-ai_score"),
            to_attr="waiting_applicants"
        )
    )

    # 4. Fetch all active job interviews in one single query
    active_interviews = (
        Interview.objects.filter(applicants__job__in=jobs)
        .prefetch_related("applicants__job")
        .distinct()
        .order_by("date", "time")
    )

    # 5. Map interviews by job_id in memory (O(1) lookups)
    interviews_by_job = defaultdict(list)
    for interview in active_interviews:
        seen_job_ids = set()
        for applicant in interview.applicants.all():
            if applicant.job_id and applicant.job_id not in seen_job_ids:
                seen_job_ids.add(applicant.job_id)
                interviews_by_job[applicant.job_id].append(interview)

    # 6. Build the job_interviews list purely in-memory
    job_interviews = []
    for job in jobs:
        # Use Python len() on the prefetched list so no extra query is executed
        waiting = len(job.waiting_applicants)
        job_interviews_list = interviews_by_job.get(job.id, [])

        # Hide jobs that have neither waiting applicants nor interviews
        if waiting == 0 and not job_interviews_list:
            continue

        job_interviews.append({
            "job": job,
            "waiting": waiting,
            "interviews": job_interviews_list,
        })

    context = {
        "total": counts["total"],
        "scheduled": counts["scheduled"],
        "ongoing": counts["ongoing"],
        "completed": counts["completed"],
        "cancelled": counts["cancelled"],

        "jobs": jobs,
        "job_interviews": job_interviews,
        "today": today,

        "todays_schedule": todays_schedule,
        "upcoming_interviews": upcoming_interviews,
        "overdue_interviews": overdue_interviews,
    }

    return render(request, "hr/interview.html", context)


@never_cache
@hr_required(login_url="hr_login")
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
        request,
        "hr/schedule_interview.html",
        {
            "job": job,
            "applicants": applicants,
            "interview": Interview,
        },
    )


@never_cache
@hr_required(login_url="hr_login")
def interview_detail(request, pk):
    interview = get_object_or_404(
        Interview.objects.prefetch_related("applicants__job"),
        pk=pk
    )

    return render(
        request,
        "hr/interview_detail.html",
        {"interview": interview}
    )
    
@never_cache
@hr_required(login_url="hr_login")
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