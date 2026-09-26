from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from jobs.models import Application, Job, Requirement, Department
from .models import Interview, CandidateEvaluation, AuditLog, HRNotification
from .utils import log_hr_action, seed_applicant_management_logs_if_empty, seed_initial_notifications_if_empty
from video_interview.models import InterviewSession, InterviewResponse
from .evaluation_ai import analyze_interview_audio
from django.db.models import Q, Count, Prefetch, F, Window, Avg
import json
from django.db.models.functions import RowNumber
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
from django.core.cache import cache
from django.views.decorators.cache import never_cache

from collections import defaultdict
import ast
import math
from urllib.parse import quote
from django.urls import reverse
import asyncio
from asgiref.sync import sync_to_async

def invalidate_hr_cache():
    """Clear short-lived cache keys when mutations occur."""
    cache.clear()

# Create your views here.
def hr_required(view_func=None, login_url="hr_login"):
    """
    Decorator for views that checks that the user is logged in, is staff,
    is not superuser, and belongs to the 'HR' group.
    - If user is not authenticated: redirects to `login_url` with ?next=...
    - If user is authenticated and HR: grants access.
    - Otherwise: raises PermissionDenied (403).
    Supports both @hr_required and @hr_required(login_url="...").
    Supports both sync and async view functions.
    """
    if isinstance(view_func, str):
        actual_login_url = view_func
        actual_view_func = None
    else:
        actual_login_url = login_url
        actual_view_func = view_func

    def decorator(view):
        if asyncio.iscoroutinefunction(view):
            @wraps(view)
            async def async_wrapper(request, *args, **kwargs):
                @sync_to_async(thread_sensitive=True)
                def check_access():
                    user = request.user
                    if not user.is_authenticated:
                        return "unauthenticated"
                    if user.is_staff and not user.is_superuser and user.groups.filter(name="HR").exists():
                        return "authorized"
                    return "forbidden"

                status = await check_access()
                if status == "unauthenticated":
                    return redirect_to_login(request.get_full_path(), actual_login_url)
                elif status == "authorized":
                    return await view(request, *args, **kwargs)
                else:
                    raise PermissionDenied
            return async_wrapper
        else:
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
                log_hr_action(
                    request,
                    action="HR_LOGIN",
                    target_repr=f"HR Staff {user.get_full_name() or user.username}",
                    details=f"HR Staff '{user.get_full_name() or user.username}' logged into HR portal.",
                    target_model="User",
                    target_id=user.pk,
                )
                return redirect("dashboard")
        
        messages.error(request, "Invalid username or password.")
        
    return render(request, "hr/login.html") 

def parse_ai_bullets(text):
    if not text:
        return []
    if isinstance(text, list):
        return [str(item).strip().lstrip("-*• ") for item in text if str(item).strip()]
    text = str(text).strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            evaluated = ast.literal_eval(text)
            if isinstance(evaluated, list):
                return [str(item).strip().lstrip("-*• ") for item in evaluated if str(item).strip()]
        except Exception:
            pass
    lines = [line.strip().lstrip("-*• ") for line in text.split("\n") if line.strip()]
    return lines

@never_cache
@hr_required
def hr_logout(request):
    if request.user.is_authenticated:
        log_hr_action(
            request,
            action="HR_LOGOUT",
            target_repr=f"HR Staff {request.user.get_full_name() or request.user.username}",
            details=f"HR Staff '{request.user.get_full_name() or request.user.username}' logged out.",
            target_model="User",
            target_id=request.user.pk,
        )
    logout(request)
    return redirect("hr_login")


@hr_required(login_url="hr_login")
def dashboard(request):
    cache_key = "hr_dashboard_data"
    content = cache.get(cache_key)
    if content is None:
        app_counts = Application.objects.aggregate(
            total=Count("id"),
            screening=Count("id", filter=Q(status="Screening")),
            hired=Count("id", filter=Q(status="Hired")),
            interview=Count("id", filter=Q(status="Interview")),
            evaluation=Count("id", filter=Q(status="Evaluation")),
            pending=Count("id", filter=Q(status="Pending")),
        )

        total_applications = app_counts["total"]
        screening = app_counts["screening"]
        hired = app_counts["hired"]
        interview = app_counts["interview"]
        evaluation = app_counts["evaluation"]
        pending_count = app_counts["pending"]
        interview_count = app_counts["interview"]

        active_jobs = Job.objects.filter(status="Active").count()

        if total_applications > 0:
            screening_percent = screening / total_applications * 100
            interview_percent = interview / total_applications * 100
            evaluation_percent = evaluation / total_applications * 100
            hired_percent = hired / total_applications * 100
        else:
            screening_percent = 0
            interview_percent = 0
            evaluation_percent = 0
            hired_percent = 0

        # 1. 6-Month Recruitment Velocity (Application Inflow & Hires)
        now = timezone.now()
        months_labels = []
        monthly_apps = []
        monthly_hires = []
        for i in range(5, -1, -1):
            m_year = now.year
            m_month = now.month - i
            while m_month <= 0:
                m_month += 12
                m_year -= 1
            dt_label = date(m_year, m_month, 1).strftime("%b %Y")
            months_labels.append(dt_label)

            app_cnt = Application.objects.filter(
                created_at__year=m_year,
                created_at__month=m_month,
            ).count()
            monthly_apps.append(app_cnt)

            hire_cnt = Application.objects.filter(
                status="Hired",
                created_at__year=m_year,
                created_at__month=m_month,
            ).count()
            monthly_hires.append(hire_cnt)

        # 2. Department Breakdown
        dept_qs = (
            Application.objects.values("job__department")
            .annotate(total=Count("id"))
            .order_by("-total")
        )
        dept_labels = []
        dept_counts = []
        for item in dept_qs:
            dept_name = (item["job__department"] or "General").strip()
            if not dept_name:
                dept_name = "General"
            dept_labels.append(dept_name)
            dept_counts.append(item["total"])

        if not dept_labels:
            dept_labels = ["No Applications"]
            dept_counts = [0]

        # 3. AI Talent Quality / Score Distribution
        score_tiers_agg = Application.objects.aggregate(
            tier_top=Count("id", filter=Q(ai_score__gte=90)),
            tier_high=Count("id", filter=Q(ai_score__gte=80, ai_score__lt=90)),
            tier_qualified=Count("id", filter=Q(ai_score__gte=70, ai_score__lt=80)),
            tier_review=Count("id", filter=Q(ai_score__lt=70)),
        )
        score_labels = ["Top Tier (90-100)", "High Potential (80-89)", "Qualified (70-79)", "Review Needed (<70)"]
        score_counts = [
            score_tiers_agg["tier_top"] or 0,
            score_tiers_agg["tier_high"] or 0,
            score_tiers_agg["tier_qualified"] or 0,
            score_tiers_agg["tier_review"] or 0,
        ]

        chart_data = {
            "months_labels": months_labels,
            "monthly_apps": monthly_apps,
            "monthly_hires": monthly_hires,
            "dept_labels": dept_labels,
            "dept_counts": dept_counts,
            "score_labels": score_labels,
            "score_counts": score_counts,
        }

        content = {
            "total_applications": total_applications,
            "screening": screening,
            "hired": hired,
            "interview": interview,
            "evaluation": evaluation,
            "active_jobs": active_jobs,
            "pending_count": pending_count,
            "interview_count": interview_count,
            "screening_percent": screening_percent,
            "interview_percent": interview_percent,
            "evaluation_percent": evaluation_percent,
            "hired_percent": hired_percent,
            "chart_data_json": json.dumps(chart_data),
        }
        cache.set(cache_key, content, 15)

    # Seed initial notifications if empty
    seed_initial_notifications_if_empty()

    # Dynamic notification counts and greeting for the logged-in HR staff
    context = dict(content)
    hr_user = request.user
    full_name = f"{hr_user.first_name} {hr_user.last_name}".strip()
    context["hr_user_name"] = full_name or hr_user.first_name or hr_user.username
    context["unread_notifs_count"] = HRNotification.objects.filter(is_read=False).count()
    context["recent_notifications"] = list(
        HRNotification.objects.all().order_by("-created_at")[:10]
    )

    return render(request, "hr/dashboard.html", context)


@hr_required(login_url="hr_login")
def hr_notifications_feed(request):
    """
    Returns latest HR notifications and unread count in JSON format for reactive updates.
    """
    seed_initial_notifications_if_empty()
    notifs_qs = HRNotification.objects.all().order_by("-created_at")[:15]
    unread_count = HRNotification.objects.filter(is_read=False).count()

    def format_time_ago(dt):
        if not dt:
            return ""
        delta = timezone.now() - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "Just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 7:
            return f"{days}d ago"
        return dt.strftime("%b %d")

    data = {
        "status": "success",
        "unread_count": unread_count,
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "type": n.notification_type,
                "link": n.link or reverse("candidates"),
                "is_read": n.is_read,
                "time_ago": format_time_ago(n.created_at),
            }
            for n in notifs_qs
        ],
    }
    return JsonResponse(data)


@hr_required(login_url="hr_login")
def mark_notification_read(request):
    """
    Marks a single notification or all notifications as read.
    """
    if request.method == "POST":
        notif_id = request.POST.get("notification_id")
        if not notif_id and request.content_type == "application/json":
            try:
                body_data = json.loads(request.body.decode("utf-8")) if request.body else {}
                notif_id = body_data.get("notification_id")
            except Exception:
                pass

        if notif_id:
            HRNotification.objects.filter(id=notif_id).update(is_read=True)
        else:
            HRNotification.objects.filter(is_read=False).update(is_read=True)

        unread_count = HRNotification.objects.filter(is_read=False).count()
        return JsonResponse({"status": "success", "unread_count": unread_count})

    return JsonResponse({"status": "error", "message": "POST required"}, status=405)

def get_job_management_context(selected_department=""):
    active_jobs = list(
        Job.objects.filter(status="Active")
        .annotate(applicant_count=Count("application", distinct=True))
        .prefetch_related("requirements_list")
        .order_by("-posted_date")
    )
    
    inactive_jobs = list(
        Job.objects.filter(status="Inactive")
        .annotate(applicant_count=Count("application", distinct=True))
        .prefetch_related("requirements_list")
        .order_by("-posted_date")
    )
    
    total_active = len(active_jobs)
    total_inactive = len(inactive_jobs)
    total_jobs = total_active + total_inactive
    
    # Retrieve all explicit departments plus any from existing jobs (both active and inactive)
    db_dept_names = set(Department.objects.values_list("name", flat=True))
    job_dept_names = set(j.department.strip() for j in (active_jobs + inactive_jobs) if j.department and j.department.strip())
    all_dept_names = sorted(list(db_dept_names | job_dept_names))
    
    # Group active jobs by department
    departments_dict = defaultdict(list)
    for job in active_jobs:
        dept = job.department.strip() if job.department and job.department.strip() else "General"
        departments_dict[dept].append(job)
        if dept not in all_dept_names:
            all_dept_names.append(dept)

    # Group inactive jobs by department
    inactive_depts_dict = defaultdict(list)
    for job in inactive_jobs:
        dept = job.department.strip() if job.department and job.department.strip() else "General"
        inactive_depts_dict[dept].append(job)
        if dept not in all_dept_names:
            all_dept_names.append(dept)
            
    all_dept_names = sorted(list(set(all_dept_names)))
    
    department_sections = []
    for dept_name in all_dept_names:
        jobs_in_dept = departments_dict.get(dept_name, [])
        inactive_in_dept = inactive_depts_dict.get(dept_name, [])
        department_sections.append({
            "name": dept_name,
            "jobs": jobs_in_dept,
            "inactive_jobs": inactive_in_dept,
            "active_count": len(jobs_in_dept),
            "inactive_count": len(inactive_in_dept),
        })

    filtered_department_sections = department_sections
    filtered_inactive_jobs = inactive_jobs
    if selected_department:
        filtered_department_sections = [
            d for d in department_sections if d["name"] == selected_department
        ]
        filtered_inactive_jobs = [
            j for j in inactive_jobs if (j.department.strip() if j.department else "General") == selected_department
        ]
        
    return {
        "active_jobs": active_jobs,
        "inactive_jobs": filtered_inactive_jobs,
        "department_sections": filtered_department_sections,
        "all_departments": all_dept_names,
        "selected_department": selected_department,
        "total_active": total_active,
        "total_inactive": total_inactive,
        "total_jobs": total_jobs,
    }

@never_cache
@hr_required(login_url="hr_login")
def create_department(request):
    if request.method == "POST":
        dept_name = request.POST.get("name", "").strip()
        if dept_name:
            dept_obj, created = Department.objects.get_or_create(name=dept_name)
            invalidate_hr_cache()
            if created:
                log_hr_action(
                    request,
                    action="DEPARTMENT_CREATED",
                    target_repr=dept_name,
                    details=f"Created new department '{dept_name}'.",
                    target_model="Department",
                    target_id=dept_obj.pk,
                )

    if request.headers.get("HX-Request"):
        data = get_job_management_context()
        response = render(request, "hr/partials/job_management_content.html", data)
        response["HX-Trigger"] = "closeDeptModal"
        return response

    messages.success(request, "New department created successfully!")
    return redirect("job_management")

@never_cache
@hr_required(login_url="hr_login")
def create_job(request):
    if request.method == "POST":
        dept_name = request.POST.get("department", "").strip()
        if dept_name:
            Department.objects.get_or_create(name=dept_name)

        job = Job.objects.create(
            title=request.POST.get("title", "").strip(),
            department=dept_name,
            job_type=request.POST.get("job_type", "FULL-TIME"),
            schedule=request.POST.get("schedule", "").strip(),
            shift=request.POST.get("shift", "").strip(),
            description=request.POST.get("description", "").strip(),
            requirements=request.POST.get("requirements", "").strip(),
            status="Active",
        )

        # Get all Key Qualifications
        key_qualifications = request.POST.getlist(
            "key_qualifications"
        )

        # Save each Key Qualification
        for qualification in key_qualifications:
            qualification = qualification.strip()

            if qualification:
                Requirement.objects.create(
                    job=job,
                    text=qualification
                )
        invalidate_hr_cache()

        log_hr_action(
            request,
            action="JOB_CREATED",
            target_repr=job.title,
            details=f"Created job posting '{job.title}' in {job.department} ({job.job_type}).",
            target_model="Job",
            target_id=job.pk,
        )

        if request.headers.get("HX-Request"):
            data = get_job_management_context()
            response = render(request, "hr/partials/job_management_content.html", data)
            response["HX-Trigger"] = "closePostModal"
            return response

        messages.success(request, "New job created successfully!")
    return redirect("job_management")

@never_cache
@hr_required(login_url="hr_login")
def job_management(request):
    selected_department = request.GET.get("department", "").strip()
    cache_key = f"hr_job_management_data_{selected_department}" if selected_department else "hr_job_management_data"
    data = cache.get(cache_key)
    if data is None:
        data = get_job_management_context(selected_department=selected_department)
        cache.set(cache_key, data, 15)
    
    if request.headers.get("HX-Request") and request.GET.get("partial") == "content":
        return render(request, "hr/partials/job_management_content.html", data)

    return render(request, "hr/job_management.html", data)

@never_cache
@hr_required(login_url="hr_login")
def manage_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == "POST":
        dept_name = request.POST.get("department", "").strip()
        job.title = request.POST.get("title", "").strip()
        job.department = dept_name
        job.job_type = request.POST.get("job_type", "FULL-TIME")
        job.schedule = request.POST.get("schedule", "").strip()
        job.shift = request.POST.get("shift", "").strip()
        job.description = request.POST.get("description", "").strip()
        job.requirements = request.POST.get("requirements", "").strip()
        job.status = request.POST.get("status", job.status)
        job.save()
        
        key_qualifications = request.POST.getlist(
            "key_qualifications"
        )
        
        job.requirements_list.all().delete()
        
        for qualification in key_qualifications:
            if qualification.strip():
                Requirement.objects.create(job=job, text=qualification.strip())
                
        invalidate_hr_cache()

        log_hr_action(
            request,
            action="JOB_UPDATED",
            target_repr=job.title,
            details=f"Updated job posting '{job.title}' in {job.department} (Status: {job.status}).",
            target_model="Job",
            target_id=job.pk,
        )

        if request.headers.get("HX-Request"):
            data = get_job_management_context()
            response = render(request, "hr/partials/job_management_content.html", data)
            response["HX-Trigger"] = "closeEditModal"
            return response

        messages.success(request, "Changes saved successfully!")
        return redirect("job_management")
        
    requirements = job.requirements_list.all()
    applicant_count = Application.objects.filter(job=job).count()
    all_depts = sorted(list(set(Department.objects.values_list("name", flat=True)) | set(Job.objects.values_list("department", flat=True))))
    
    context = {
        "job": job,
        "key_qualifications": requirements,
        "requirements": requirements,
        "applicant_count": applicant_count,
        "all_departments": all_depts,
    }

    if request.headers.get("HX-Request"):
        return render(request, "hr/partials/edit_job_modal.html", context)

    return render(request, "hr/manage_job.html", context)

TABLE_PAGE_SIZE = 5

def get_job_candidates_table_context(job, search_query="", page_number=1):
    """
    Returns pagination and candidate slice for the table below top 3 cards.
    In default mode: candidates rank 4 to 8 on page 1, 9 to 13 on page 2, etc.
    In search mode: candidates matching search query for this job, paginated 5 per page.
    """
    try:
        page_number = int(page_number)
        if page_number < 1:
            page_number = 1
    except (ValueError, TypeError):
        page_number = 1

    base_fields = (
        "id", "application_id", "first_name", "middle_initial", "last_name",
        "email", "phone", "ai_score", "status", "created_at", "job_id"
    )

    if search_query:
        search_qs = (
            Application.objects.filter(job=job)
            .filter(
                Q(application_id__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(email__icontains=search_query)
            )
            .only(*base_fields)
            .order_by("-ai_score", "-created_at", "id")
        )
        total_matching = search_qs.count()
        total_pages = max(1, math.ceil(total_matching / TABLE_PAGE_SIZE)) if total_matching > 0 else 1
        page_number = min(page_number, total_pages)

        offset = (page_number - 1) * TABLE_PAGE_SIZE
        candidates_page = list(search_qs[offset : offset + TABLE_PAGE_SIZE])

        if candidates_page:
            all_job_app_ids = list(
                Application.objects.filter(job=job)
                .order_by("-ai_score", "-created_at", "id")
                .values_list("id", flat=True)
            )
            rank_map = {app_id: idx + 1 for idx, app_id in enumerate(all_job_app_ids)}
            for cand in candidates_page:
                cand.table_rank = rank_map.get(cand.id, 1)

        start_idx = offset + 1 if total_matching > 0 else 0
        end_idx = min(offset + TABLE_PAGE_SIZE, total_matching)

        return {
            "job": job,
            "candidates": candidates_page,
            "is_search": True,
            "search_query": search_query,
            "total_count": total_matching,
            "start_index": start_idx,
            "end_index": end_idx,
            "current_page": page_number,
            "total_pages": total_pages,
            "has_previous": page_number > 1,
            "has_next": page_number < total_pages,
            "previous_page": page_number - 1,
            "next_page": page_number + 1,
            "page_range": range(1, total_pages + 1),
        }
    else:
        total_apps = job.applicant_count if hasattr(job, "applicant_count") else Application.objects.filter(job=job).count()
        total_table_candidates = max(0, total_apps - 3)
        total_pages = max(1, math.ceil(total_table_candidates / TABLE_PAGE_SIZE)) if total_table_candidates > 0 else 1
        page_number = min(page_number, total_pages)

        offset = 3 + (page_number - 1) * TABLE_PAGE_SIZE
        candidates_page = list(
            Application.objects.filter(job=job)
            .only(*base_fields)
            .order_by("-ai_score", "-created_at", "id")[offset : offset + TABLE_PAGE_SIZE]
        )

        for idx, cand in enumerate(candidates_page):
            cand.table_rank = offset + idx + 1

        start_idx = offset + 1 if total_table_candidates > 0 else 0
        end_idx = min(offset + TABLE_PAGE_SIZE, total_apps)

        return {
            "job": job,
            "candidates": candidates_page,
            "is_search": False,
            "search_query": "",
            "total_count": total_apps,
            "total_table_candidates": total_table_candidates,
            "start_index": start_idx,
            "end_index": end_idx,
            "current_page": page_number,
            "total_pages": total_pages,
            "has_previous": page_number > 1,
            "has_next": page_number < total_pages,
            "previous_page": page_number - 1,
            "next_page": page_number + 1,
            "page_range": range(1, total_pages + 1),
        }

@never_cache
@hr_required(login_url="hr_login")
def candidates(request):
    selected_department = request.GET.get("department", "").strip()
    selected_job = request.GET.get("job", "").strip()
    active_tab = request.GET.get("tab", "all").strip().lower()
    if active_tab not in ["all", "recent"]:
        active_tab = "all"

    # Recent candidate submissions across all jobs
    recent_applications = list(
        Application.objects.select_related("job")
        .only(
            "id", "application_id", "first_name", "middle_initial", "last_name",
            "email", "phone", "ai_score", "status", "created_at",
            "job__id", "job__title", "job__department"
        )
        .order_by("-created_at", "-id")[:50]
    )

    # Single aggregate query for all candidate status counts
    counts = Application.objects.aggregate(
        total=Count("id"),
        screening=Count("id", filter=Q(status="Screening")),
        interview=Count("id", filter=Q(status__in=["Interview", "Shortlisted"])),
        evaluation=Count("id", filter=Q(status="Evaluation")),
        hired=Count("id", filter=Q(status="Hired")),
    )

    # All active jobs that currently have applicants
    active_jobs_with_apps = list(
        Job.objects.filter(status="Active")
        .annotate(applicant_count=Count("application"))
        .filter(applicant_count__gt=0)
        .order_by("department", "title")
    )

    # Distinct departments that have applicants
    available_departments = sorted(list(set(j.department for j in active_jobs_with_apps)))

    filtered_jobs = active_jobs_with_apps
    if selected_department:
        filtered_jobs = [j for j in filtered_jobs if j.department == selected_department]
    if selected_job and selected_job.isdigit():
        target_job_id = int(selected_job)
        filtered_jobs = [j for j in filtered_jobs if j.id == target_job_id]

    base_candidate_fields = (
        "id", "application_id", "first_name", "middle_initial", "last_name",
        "email", "phone", "ai_score", "status", "created_at", "job_id"
    )

    filtered_job_ids = [j.id for j in filtered_jobs]
    top_candidates_by_job = defaultdict(list)
    table_candidates_by_job = defaultdict(list)

    if filtered_job_ids:
        # 1. Fetch top 3 candidates for ALL filtered jobs in 1 single partitioned query
        top_cands_qs = (
            Application.objects.filter(job_id__in=filtered_job_ids)
            .annotate(
                row_num=Window(
                    expression=RowNumber(),
                    partition_by=[F("job_id")],
                    order_by=[F("ai_score").desc(), F("created_at").desc(), F("id").asc()]
                )
            )
            .filter(row_num__lte=3)
            .only(*base_candidate_fields)
        )
        for cand in top_cands_qs:
            top_candidates_by_job[cand.job_id].append(cand)

        # 2. Fetch table candidates (ranks 4 to 8) for ALL filtered jobs in 1 single partitioned query
        table_cands_qs = (
            Application.objects.filter(job_id__in=filtered_job_ids)
            .annotate(
                row_num=Window(
                    expression=RowNumber(),
                    partition_by=[F("job_id")],
                    order_by=[F("ai_score").desc(), F("created_at").desc(), F("id").asc()]
                )
            )
            .filter(row_num__gte=4, row_num__lte=8)
            .only(*base_candidate_fields)
        )
        for cand in table_cands_qs:
            cand.table_rank = cand.row_num
            table_candidates_by_job[cand.job_id].append(cand)

    # Group jobs by department and assign top 3 cards + initial table context for each job
    departments_dict = defaultdict(list)
    for job in filtered_jobs:
        top_candidates = top_candidates_by_job.get(job.id, [])
        for idx, cand in enumerate(top_candidates):
            cand.top_rank = idx + 1
        job.top_candidates = top_candidates

        total_apps = job.applicant_count if hasattr(job, "applicant_count") else len(top_candidates)
        total_table_candidates = max(0, total_apps - 3)
        total_pages = max(1, math.ceil(total_table_candidates / TABLE_PAGE_SIZE)) if total_table_candidates > 0 else 1
        
        table_page = table_candidates_by_job.get(job.id, [])
        job.table_data = {
            "job": job,
            "candidates": table_page,
            "is_search": False,
            "search_query": "",
            "total_count": total_apps,
            "total_table_candidates": total_table_candidates,
            "start_index": 4 if total_table_candidates > 0 else 0,
            "end_index": min(3 + len(table_page), total_apps),
            "current_page": 1,
            "total_pages": total_pages,
            "has_previous": False,
            "has_next": total_pages > 1,
            "previous_page": 1,
            "next_page": 2,
            "page_range": range(1, total_pages + 1),
        }
        departments_dict[job.department].append(job)

    department_sections = []
    for dept_name, jobs_list in departments_dict.items():
        total_dept_applicants = sum(j.applicant_count for j in jobs_list)
        all_dept_jobs = [
            {"id": j.id, "title": j.title}
            for j in active_jobs_with_apps
            if j.department == dept_name
        ]
        department_sections.append({
            "name": dept_name,
            "jobs": jobs_list,
            "all_jobs": all_dept_jobs,
            "job_count": len(jobs_list),
            "total_applicants": total_dept_applicants,
        })

    return render(request, "hr/candidates.html", {
        "department_sections": department_sections,
        "available_departments": available_departments,
        "selected_department": selected_department,
        "selected_job": selected_job,
        "total_candidates": counts["total"],
        "screening_count": counts["screening"],
        "interview_count": counts["interview"],
        "evaluation_count": counts["evaluation"],
        "hired_count": counts["hired"],
        "active_tab": active_tab,
        "recent_applications": recent_applications,
        "recent_applications_count": len(recent_applications),
    })

@never_cache
@hr_required(login_url="hr_login")
def candidate_job_table(request, job_id):
    job = get_object_or_404(
        Job.objects.annotate(applicant_count=Count("application")),
        id=job_id
    )
    search_query = request.GET.get("search", "").strip()
    page_number = request.GET.get("page", 1)

    table_data = get_job_candidates_table_context(job, search_query=search_query, page_number=page_number)
    return render(
        request,
        "hr/partials/candidate_job_table.html",
        {"table_data": table_data, "job": job}
    )

@never_cache
@hr_required(login_url="hr_login")
def candidate_department(request, department):
    return redirect(f"{reverse('candidates')}?department={quote(department)}")

@never_cache
@hr_required(login_url="hr_login")
def candidate_detail(request, pk):
    application = get_object_or_404(
        Application.objects.select_related("job", "applicant"),
        pk=pk
    )

    # Normalize legacy Pending status to Screening
    if application.status == "Pending":
        application.status = "Screening"
        application.save(update_fields=["status"])
        invalidate_hr_cache()

    # Auto re-analyze candidate with AI if score is 0, pending, or not yet processed
    has_resume = bool(application.resume or (application.applicant and application.applicant.default_resume))
    if has_resume and (not application.resume_processed or application.ai_score == 0 or application.ai_recommendation == "Pending Review"):
        try:
            from jobs.ai import screen_application
            screen_application(application, max_retries=2)
            application.refresh_from_db()
        except Exception as auto_err:
            import logging
            logging.getLogger(__name__).warning(
                "Auto re-analysis on candidate_detail failed for app %s: %s",
                getattr(application, "application_id", application.id),
                auto_err,
            )
    
    strengths = parse_ai_bullets(application.ai_strengths)
    weaknesses = parse_ai_bullets(application.ai_weaknesses)

    interview_session = InterviewSession.objects.filter(
        application=application
    ).prefetch_related(
        Prefetch("responses", queryset=InterviewResponse.objects.order_by("question_number"))
    ).first()

    interview_responses = list(interview_session.responses.all()) if interview_session else []

    candidate_evaluation = getattr(application, "evaluation", None)
    if candidate_evaluation is None:
        try:
            candidate_evaluation = CandidateEvaluation.objects.filter(application=application).first()
        except Exception:
            candidate_evaluation = None

    scheduled_interviews = list(application.interview.all().order_by("-date", "-time"))
    scheduled_interview = scheduled_interviews[0] if scheduled_interviews else None

    # Calculate true AI match rank of the candidate within this job role
    all_job_app_ids = list(
        Application.objects.filter(job=application.job)
        .order_by("-ai_score", "-created_at", "id")
        .values_list("id", flat=True)
    )
    try:
        candidate_rank = all_job_app_ids.index(application.id) + 1
    except ValueError:
        candidate_rank = None
    total_job_applicants = len(all_job_app_ids)

    # Determine whether the evaluation form should be open or show the "not initiated" banner
    evaluate_param = request.GET.get("evaluate") == "1"
    is_draft = bool(candidate_evaluation and candidate_evaluation.status == "Draft")
    show_eval_form = evaluate_param or is_draft
    
    return render(request, "hr/candidate_detail.html", {
        "application": application,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "interview_session": interview_session,
        "interview_responses": interview_responses,
        "candidate_evaluation": candidate_evaluation,
        "scheduled_interviews": scheduled_interviews,
        "scheduled_interview": scheduled_interview,
        "candidate_rank": candidate_rank,
        "total_job_applicants": total_job_applicants,
        "show_eval_form": show_eval_form,
    })


@never_cache
@hr_required(login_url="hr_login")
def reset_candidate_interview(request, pk):
    application = get_object_or_404(Application, pk=pk)
    session = InterviewSession.objects.filter(application=application).first()
    if session:
        session.can_retake = True
        session.status = "PENDING"
        session.save()
        log_hr_action(
            request,
            action="EVALUATION_RESET",
            target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
            details=f"Video interview for {application.first_name} {application.last_name} was reset to allow retake.",
            target_model="InterviewSession",
            target_id=session.pk,
        )
        messages.success(
            request,
            f"Video interview for {application.first_name} {application.last_name} has been reset to allow a retake."
        )
    return redirect("candidate_detail", pk=pk)


@never_cache
@hr_required(login_url="hr_login")
def reanalyze_candidate_interview(request, pk):
    application = get_object_or_404(Application, pk=pk)
    session = InterviewSession.objects.filter(application=application).first()
    if session and session.status == "COMPLETED":
        try:
            from video_interview.ai import analyze_interview_session
            analyze_interview_session(session)
            messages.success(
                request,
                f"Video interview for {application.first_name} {application.last_name} was re-analyzed by Gemini AI successfully."
            )
        except Exception as e:
            messages.error(
                request,
                f"Failed to re-analyze video interview: {e}"
            )
    else:
        messages.warning(request, "Only completed interview sessions can be analyzed.")
    return redirect("candidate_detail", pk=pk)


@hr_required(login_url="hr_login")
def update_application_status(request, pk):
    application = get_object_or_404(Application, pk=pk)
    
    if request.method == "POST":
        old_status = application.status
        new_status = request.POST.get("status")
        if new_status and new_status != old_status:
            application.status = new_status
            application.save()
            invalidate_hr_cache()

            action_key = "STATUS_CHANGE"
            if new_status == "Rejected":
                action_key = "REJECT_APPLICATION"
            elif new_status == "Shortlisted":
                action_key = "SHORTLIST_APPLICATION"
            elif new_status == "Hired":
                action_key = "HIRE_APPLICATION"

            log_hr_action(
                request,
                action=action_key,
                target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
                details=f"Application status changed from '{old_status}' to '{new_status}' for position {application.job.title}.",
                target_model="Application",
                target_id=application.pk,
            )
        
    return redirect(request.META.get("HTTP_REFERER", "candidates"))


@never_cache
@hr_required(login_url="hr_login")
def restore_candidate(request, pk):
    """
    Restores a rejected or cancelled application back to Screening stage.
    """
    application = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        target_stage = request.POST.get("target_stage", "Screening")
        if target_stage not in ["Screening", "Shortlisted"]:
            target_stage = "Screening"

        old_status = application.status
        application.status = target_stage
        application.save(update_fields=["status"])
        invalidate_hr_cache()

        log_hr_action(
            request,
            action="STATUS_CHANGE",
            target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
            details=f"Application restored from '{old_status}' back to '{target_stage}'.",
            target_model="Application",
            target_id=application.pk,
        )
        messages.success(
            request,
            f"Application for {application.first_name} {application.last_name} has been restored to {target_stage}."
        )
        return redirect(f"{reverse('reports')}?tab=cancelled")

    return redirect(f"{reverse('reports')}?tab=cancelled")


@never_cache
@hr_required(login_url="hr_login")
def send_candidate_email(request, pk):
    application = get_object_or_404(Application, pk=pk)

    if request.method == "POST":
        subject = request.POST.get("subject", "").strip()
        body = request.POST.get("message", "").strip()
        recipient_email = request.POST.get("recipient_email", "").strip() or application.email

        if not subject or not body:
            messages.error(request, "Email subject and message cannot be empty.")
            return redirect("candidate_detail", pk=pk)

        html_content = (
            f"<div style='font-family: Arial, sans-serif; font-size: 14px; color: #333; line-height: 1.6;'>"
            f"{body.replace(chr(10), '<br>')}"
            f"</div>"
        )

        from main.emailer import send_gmail_message
        result = send_gmail_message(
            to_email=recipient_email,
            subject=subject,
            html_content=html_content,
            text_content=body,
        )

        if result.get("success"):
            log_hr_action(
                request,
                action="EMAIL_SENT",
                target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
                details=f"Sent candidate email '{subject}' to {recipient_email}.",
                target_model="Application",
                target_id=application.pk,
            )
            messages.success(request, f"Email successfully sent to {recipient_email}!")
        else:
            err = result.get("error", "Gmail API not configured or failed.")
            messages.warning(request, f"Could not send email automatically ({err}). Please use desktop email.")

    return redirect("candidate_detail", pk=pk)

@never_cache
@hr_required(login_url="hr_login")
def interviews(request):
    # 1. Combine 5 separate COUNT queries into 1 single aggregate query
    counts = Interview.objects.aggregate(
        total=Count("id"),
        scheduled=Count("id", filter=Q(status__in=["Scheduled", "Rescheduled"])),
        ongoing=Count("id", filter=Q(status="Ongoing")),
        completed=Count("id", filter=Q(status="Completed")),
        cancelled=Count("id", filter=Q(status="Cancelled")),
    )

    today = timezone.localdate()
    three_days = today + timedelta(days=3)

    # 2. Consolidated query for today's, upcoming, and overdue interviews (1 query + 1 prefetch)
    all_interviews = list(
        Interview.objects.filter(
            Q(date=today) |
            Q(date__gt=today, date__lte=three_days) |
            Q(date__lt=today, status__in=["Scheduled", "Rescheduled", "Ongoing"])
        )
        .prefetch_related("applicants__job")
        .order_by("date", "time")
    )

    todays_schedule = [i for i in all_interviews if i.date == today]
    todays_schedule.sort(key=lambda x: x.time)

    upcoming_interviews = [i for i in all_interviews if today < i.date <= three_days]
    overdue_interviews = [i for i in all_interviews if i.date < today and i.status in ("Scheduled", "Rescheduled", "Ongoing")]

    # 3. Prefetch waiting applicants into `waiting_applicants` attribute on each job
    jobs = list(Job.objects.filter(status="Active").prefetch_related(
        Prefetch(
            "application",
            queryset=Application.objects.filter(
                Q(status="Shortlisted") | Q(status="Interview", interview__isnull=True)
            ).order_by("-ai_score"),
            to_attr="waiting_applicants"
        )
    ))

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

    # 7. Collect scheduled applications grouped by Department and Position for the Evaluation section
    scheduled_applications = list(
        Application.objects.filter(interview__isnull=False)
        .select_related("job", "evaluation")
        .prefetch_related(
            Prefetch(
                "interview",
                queryset=Interview.objects.order_by("-date", "-time"),
                to_attr="ordered_interviews"
            )
        )
        .distinct()
        .order_by("job__department", "job__title", "-ai_score")
    )

    evaluation_dept_dict = defaultdict(lambda: defaultdict(list))
    eval_ready_total = 0
    eval_rescheduled_total = 0
    eval_ongoing_total = 0
    eval_completed_total = 0

    for app in scheduled_applications:
        if not hasattr(app, "ordered_interviews") or not app.ordered_interviews:
            continue
        latest_intv = app.ordered_interviews[0]
        app.active_interview = latest_intv

        # Determine individual candidate evaluation status
        has_eval = hasattr(app, "evaluation") and app.evaluation is not None
        if has_eval and app.evaluation.status == "Completed":
            app.candidate_status = "Completed"
        elif has_eval and app.evaluation.status == "Draft":
            app.candidate_status = "Ongoing"
        elif latest_intv.status == "Rescheduled":
            app.candidate_status = "Rescheduled"
        else:
            app.candidate_status = "Scheduled"

        dept_name = app.job.department if (app.job and app.job.department) else "General"
        job_obj = app.job
        evaluation_dept_dict[dept_name][job_obj].append(app)

        if app.candidate_status == "Rescheduled":
            eval_rescheduled_total += 1
            eval_ready_total += 1
        elif app.candidate_status == "Scheduled":
            eval_ready_total += 1
        elif app.candidate_status == "Ongoing":
            eval_ongoing_total += 1
        elif app.candidate_status == "Completed":
            eval_completed_total += 1

    evaluation_departments = []
    for dept_name in sorted(evaluation_dept_dict.keys()):
        job_map = evaluation_dept_dict[dept_name]
        dept_jobs = []
        dept_total = 0
        dept_ready = 0
        dept_ongoing = 0
        dept_completed = 0
        for job_obj, app_list in job_map.items():
            for idx, a in enumerate(app_list):
                a.table_rank = idx + 1
            job_ready = sum(1 for a in app_list if getattr(a, "candidate_status", "Scheduled") in ("Scheduled", "Rescheduled"))
            job_ongoing = sum(1 for a in app_list if getattr(a, "candidate_status", "Scheduled") == "Ongoing")
            job_completed = sum(1 for a in app_list if getattr(a, "candidate_status", "Scheduled") == "Completed")
            job_rescheduled = sum(1 for a in app_list if getattr(a, "candidate_status", "Scheduled") == "Rescheduled")
            dept_jobs.append({
                "job": job_obj,
                "applicants": app_list,
                "total_count": len(app_list),
                "ready_count": job_ready,
                "ongoing_count": job_ongoing,
                "completed_count": job_completed,
                "rescheduled_count": job_rescheduled,
            })
            dept_total += len(app_list)
            dept_ready += job_ready
            dept_ongoing += job_ongoing
            dept_completed += job_completed

        evaluation_departments.append({
            "name": dept_name,
            "jobs": dept_jobs,
            "all_jobs": [{"id": j["job"].id, "title": j["job"].title} for j in dept_jobs],
            "job_count": len(dept_jobs),
            "total_applicants": dept_total,
            "ready_count": dept_ready,
            "ongoing_count": dept_ongoing,
            "completed_count": dept_completed,
        })

    # 8. Collect applications waiting for interview scheduling grouped by Department and Position
    waiting_applications = list(
        Application.objects.filter(
            Q(status="Shortlisted") | Q(status="Interview", interview__isnull=True)
        )
        .select_related("job", "applicant")
        .order_by("job__department", "job__title", "-ai_score")
    )

    waiting_dept_dict = defaultdict(lambda: defaultdict(list))
    waiting_total = 0
    for app in waiting_applications:
        dept_name = app.job.department if (app.job and app.job.department) else "General"
        waiting_dept_dict[dept_name][app.job].append(app)
        waiting_total += 1

    waiting_departments = []
    for dept_name in sorted(waiting_dept_dict.keys()):
        job_map = waiting_dept_dict[dept_name]
        dept_jobs = []
        dept_total = 0
        for job_obj, app_list in job_map.items():
            for idx, a in enumerate(app_list):
                a.table_rank = idx + 1
            dept_jobs.append({
                "job": job_obj,
                "applicants": app_list,
                "total_count": len(app_list),
            })
            dept_total += len(app_list)
        waiting_departments.append({
            "name": dept_name,
            "jobs": dept_jobs,
            "all_jobs": [{"id": j["job"].id, "title": j["job"].title} for j in dept_jobs],
            "job_count": len(dept_jobs),
            "total_applicants": dept_total,
        })

    # 9. Aggregate today's interviews by Department and Position for Today's Schedule view
    today_dept_map = defaultdict(lambda: {"job": None, "department": "", "count": 0, "applicants": [], "interviews": []})
    for interview in todays_schedule:
        job = interview.primary_job
        if not job:
            continue
        dept = job.department or "General"
        key = (dept, job.id)
        today_dept_map[key]["job"] = job
        today_dept_map[key]["department"] = dept
        apps = list(interview.applicants.all())
        today_dept_map[key]["count"] += len(apps)
        today_dept_map[key]["applicants"].extend(apps)
        today_dept_map[key]["interviews"].append(interview)

    today_dept_positions = list(today_dept_map.values())

    # 10. HR Staff list for scheduling panel selection
    hr_staff = list(User.objects.filter(groups__name="HR", is_active=True).order_by("first_name", "last_name"))
    if not hr_staff:
        hr_staff = list(User.objects.filter(is_staff=True, is_active=True).order_by("first_name", "last_name"))

    active_tab = request.GET.get("tab", "schedules")
    if active_tab not in ("schedules", "waiting", "evaluations"):
        active_tab = "schedules"

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
        "today_dept_positions": today_dept_positions,
        "upcoming_interviews": upcoming_interviews,
        "overdue_interviews": overdue_interviews,

        "waiting_departments": waiting_departments,
        "waiting_total": waiting_total,

        "evaluation_departments": evaluation_departments,
        "eval_ready_total": eval_ready_total,
        "eval_rescheduled_total": eval_rescheduled_total,
        "eval_ongoing_total": eval_ongoing_total,
        "eval_completed_total": eval_completed_total,
        "eval_total": len(scheduled_applications),

        "hr_staff": hr_staff,
        "active_tab": active_tab,
    }

    return render(request, "hr/interview.html", context)


@never_cache
@hr_required(login_url="hr_login")
def schedule_interview(request, job_id):
    job = get_object_or_404(Job, pk=job_id)

    if request.method == "POST":
        ids = request.POST.getlist("applicants")
        if not ids:
            messages.warning(request, "No candidates were selected for batch scheduling.")
            return redirect(f"{reverse('interviews')}?tab=waiting")

        interview_type = request.POST.get("interview_type", "HR Interview")
        interviewer = request.POST.get("interviewer", "").strip() or (request.user.get_full_name() or request.user.username)
        date = request.POST.get("date")
        base_time = request.POST.get("time")
        location = request.POST.get("location", "").strip()
        notes = request.POST.get("notes", "").strip()

        if not date or not base_time:
            messages.error(request, "Please provide the scheduled date and default start time.")
            return redirect(f"{reverse('interviews')}?tab=waiting")

        # Group selected applicants by effective time
        # If applicant_time_<id> is provided, use it; otherwise fallback to base_time
        time_to_applicants = defaultdict(list)
        for app_id in ids:
            cand_time = request.POST.get(f"applicant_time_{app_id}", "").strip()
            effective_time = cand_time if cand_time else base_time
            time_to_applicants[effective_time].append(app_id)

        # Create Interview record(s) for each time slot
        for slot_time, slot_app_ids in time_to_applicants.items():
            interview = Interview.objects.create(
                interview_type=interview_type,
                interviewer=interviewer,
                date=date,
                time=slot_time,
                location=location,
                notes=notes,
                status="Scheduled",
            )
            interview.applicants.set(slot_app_ids)

        # Automatically move scheduled applicants to Interview stage
        Application.objects.filter(id__in=ids).update(
            status="Interview",
            interview_scheduled=True
        )
        invalidate_hr_cache()

        log_hr_action(
            request,
            action="INTERVIEW_SCHEDULED",
            target_repr=f"Batch for {job.title} ({len(ids)} candidates)",
            details=f"Batch scheduled {interview_type} on {date} with interviewer {interviewer}.",
            target_model="Job",
            target_id=job.pk,
        )

        messages.success(
            request,
            f"Successfully batch scheduled interview for {len(ids)} candidate(s) in {job.title}. They are now ready for evaluation."
        )
        return redirect(f"{reverse('interviews')}?tab=evaluations")

    return redirect(f"{reverse('interviews')}?tab=waiting")


@never_cache
@hr_required(login_url="hr_login")
def move_to_interview_waiting(request, pk):
    """
    Called from candidate profile confirmation popup when HR decides to advance
    a candidate from Screening stage into Interview scheduling pipeline.
    Marks candidate as Shortlisted and moves them to Candidates Waiting for Interview scheduling.
    """
    application = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        application.status = "Shortlisted"
        application.interview_scheduled = False
        application.save(update_fields=["status", "interview_scheduled"])
        invalidate_hr_cache()

        log_hr_action(
            request,
            action="SHORTLIST_APPLICATION",
            target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
            details=f"Shortlisted candidate and moved to Interview waiting pipeline.",
            target_model="Application",
            target_id=application.pk,
        )

        messages.success(
            request,
            f"{application.first_name} {application.last_name} has been shortlisted and moved to Candidates Waiting for Interview scheduling."
        )
    return redirect(f"{reverse('interviews')}?tab=waiting")


@never_cache
@hr_required(login_url="hr_login")
def schedule_candidate_interview(request):
    """
    Called from Candidates Waiting for Interview tab to schedule an interview session
    for one or more candidates applying for a position.
    """
    if request.method == "POST":
        interview_type = request.POST.get("interview_type", "HR Interview")
        interviewer = request.POST.get("interviewer", "").strip()
        date_str = request.POST.get("date")
        time_str = request.POST.get("time")
        location = request.POST.get("location", "").strip()
        notes = request.POST.get("notes", "").strip()

        applicant_ids = request.POST.getlist("applicants")
        if not applicant_ids and request.POST.get("applicant_id"):
            applicant_ids = [request.POST.get("applicant_id")]

        if not date_str or not time_str or not applicant_ids:
            messages.error(request, "Please provide the interview date, time, and select at least one candidate.")
            return redirect(f"{reverse('interviews')}?tab=waiting")

        interviewer_name = interviewer or request.user.get_full_name() or request.user.username
        interview = Interview.objects.create(
            interview_type=interview_type,
            interviewer=interviewer_name,
            date=date_str,
            time=time_str,
            location=location,
            notes=notes,
            status="Scheduled",
        )
        interview.applicants.set(applicant_ids)
        Application.objects.filter(id__in=applicant_ids).update(
            status="Interview",
            interview_scheduled=True
        )
        invalidate_hr_cache()

        log_hr_action(
            request,
            action="INTERVIEW_SCHEDULED",
            target_repr=f"{len(applicant_ids)} candidate(s)",
            details=f"Scheduled {interview_type} on {date_str} at {time_str} with {interviewer_name}.",
            target_model="Interview",
            target_id=interview.pk,
        )

        messages.success(
            request,
            f"Interview successfully scheduled for {len(applicant_ids)} candidate(s). They are now ready for evaluation."
        )
        return redirect(f"{reverse('interviews')}?tab=evaluations")

    return redirect(f"{reverse('interviews')}?tab=waiting")


@never_cache
@hr_required(login_url="hr_login")
def reschedule_candidate_interview(request, pk):
    """
    Called from Candidates Waiting for Interview tab to reschedule an interview
    with updated date, time, logistics, and timestamped per-applicant notes.
    """
    application = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        new_date = request.POST.get("date")
        new_time = request.POST.get("time")
        location = request.POST.get("location", "").strip()
        interviewer = request.POST.get("interviewer", "").strip()
        reschedule_notes = request.POST.get("reschedule_notes", "").strip()

        interview = application.interview.order_by("-date", "-time").first()
        interviewer_name = interviewer or (interview.interviewer if interview else (request.user.get_full_name() or request.user.username))

        if not interview:
            interview = Interview.objects.create(
                interview_type=request.POST.get("interview_type", "HR Interview"),
                interviewer=interviewer_name,
                date=new_date,
                time=new_time,
                location=location,
                notes=f"Rescheduled: {reschedule_notes}" if reschedule_notes else "",
                status="Rescheduled",
            )
            interview.applicants.add(application)
        else:
            if new_date:
                interview.date = new_date
            if new_time:
                interview.time = new_time
            if location:
                interview.location = location
            if interviewer:
                interview.interviewer = interviewer
            interview.status = "Rescheduled"
            if reschedule_notes:
                stamp = timezone.localtime().strftime("%b %d, %Y %I:%M %p")
                note_entry = f"[Rescheduled on {stamp}]: {reschedule_notes}"
                interview.notes = f"{interview.notes}\n{note_entry}".strip() if interview.notes else note_entry
            interview.save()

        application.interview_scheduled = True
        application.status = "Interview"
        application.save(update_fields=["status", "interview_scheduled"])
        invalidate_hr_cache()

        log_hr_action(
            request,
            action="INTERVIEW_RESCHEDULED",
            target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
            details=f"Interview rescheduled to {new_date} at {new_time}. Notes: {reschedule_notes or 'None'}",
            target_model="Application",
            target_id=application.pk,
        )

        messages.success(
            request,
            f"Interview for {application.first_name} {application.last_name} has been rescheduled to {new_date}."
        )

        next_tab = request.POST.get("next_tab", "waiting")
        return redirect(f"{reverse('interviews')}?tab={next_tab}")

    return redirect(f"{reverse('interviews')}?tab=waiting")


@never_cache
@hr_required(login_url="hr_login")
def cancel_candidate_interview(request, pk):
    """
    Called to cancel an interview,
    recording cancellation notes per applicant and handling status transition.
    """
    application = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        cancel_notes = request.POST.get("cancel_notes", "").strip()
        cancel_action = request.POST.get("cancel_action", "cancel_interview")

        interview = application.interview.order_by("-date", "-time").first()
        if interview:
            stamp = timezone.localtime().strftime("%b %d, %Y %I:%M %p")
            note_entry = f"[Cancelled on {stamp} for {application.first_name} {application.last_name}]: {cancel_notes}".strip()
            interview.notes = f"{interview.notes}\n{note_entry}".strip() if interview.notes else note_entry
            if interview.applicants.count() <= 1:
                interview.status = "Cancelled"
            interview.applicants.remove(application)
            interview.save()

        if cancel_action == "reject":
            application.status = "Rejected"
        else:
            application.status = "Shortlisted"
        application.interview_scheduled = False
        application.save(update_fields=["status", "interview_scheduled"])
        invalidate_hr_cache()

        log_hr_action(
            request,
            action="INTERVIEW_CANCELLED",
            target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
            details=f"Interview cancelled. Action: {cancel_action}. Notes: {cancel_notes or 'No notes provided'}",
            target_model="Application",
            target_id=application.pk,
        )
        if cancel_action == "reject":
            log_hr_action(
                request,
                action="REJECT_APPLICATION",
                target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
                details=f"Candidate marked as Rejected following interview cancellation. Reason: {cancel_notes or 'Disqualified during interview stage'}",
                target_model="Application",
                target_id=application.pk,
            )

        messages.info(
            request,
            f"Interview for {application.first_name} {application.last_name} has been cancelled with recorded notes."
        )
        next_tab = request.POST.get("next_tab", "waiting")
        return redirect(f"{reverse('interviews')}?tab={next_tab}")

    return redirect(f"{reverse('interviews')}?tab=waiting")


@never_cache
@hr_required(login_url="hr_login")
def interview_detail(request, pk):
    """Legacy session detail endpoint redirected to Candidates Ready for Evaluation tab."""
    return redirect(f"{reverse('interviews')}?tab=evaluations")


@never_cache
@hr_required(login_url="hr_login")
def evaluate_candidate(request, pk):
    """
    Submits or updates a candidate interview evaluation (F2F, Online, Call),
    including rubric ratings, notes, audio recording, and AI audio intelligence.
    Automatically moves candidate to the 'Evaluation' stage.
    """
    application = get_object_or_404(
        Application.objects.select_related("job"),
        pk=pk
    )

    if request.method == "POST":
        evaluation, _ = CandidateEvaluation.objects.get_or_create(application=application)

        evaluator_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
        evaluation.evaluator = request.user
        evaluation.evaluator_name = evaluator_name
        evaluation.interview_mode = request.POST.get("interview_mode", "Face-to-Face")

        if not evaluation.interview:
            evaluation.interview = application.interview.order_by("-date", "-time").first()

        eval_date_str = request.POST.get("evaluation_date")
        if eval_date_str:
            try:
                evaluation.evaluation_date = eval_date_str
            except Exception:
                pass

        try:
            evaluation.technical_competence = int(request.POST.get("technical_competence", 3))
            evaluation.communication_skills = int(request.POST.get("communication_skills", 3))
            evaluation.problem_solving = int(request.POST.get("problem_solving", 3))
            evaluation.cultural_fit = int(request.POST.get("cultural_fit", 3))
            evaluation.leadership_potential = int(request.POST.get("leadership_potential", 3))
        except (ValueError, TypeError):
            pass

        evaluation.strengths_notes = request.POST.get("strengths_notes", "").strip()
        evaluation.weaknesses_notes = request.POST.get("weaknesses_notes", "").strip()
        evaluation.general_notes = request.POST.get("general_notes", "").strip()

        evaluation.expected_salary = request.POST.get("expected_salary", "").strip()
        evaluation.notice_period = request.POST.get("notice_period", "").strip()
        evaluation.availability_date = request.POST.get("availability_date", "").strip()

        rec = request.POST.get("recommendation", "Hire")
        if rec in ["Strong Hire", "Hire", "Hold", "No Hire"]:
            evaluation.recommendation = rec

        evaluation.status = "Completed"

        # Handle uploaded audio recording or live recorded audio blob
        audio_file = request.FILES.get("audio_file")
        if audio_file:
            evaluation.audio_file = audio_file

        evaluation.save()

        # Trigger Gemini AI audio analysis if audio is present and requested
        run_ai = (request.POST.get("run_ai_audio") == "1") or (audio_file is not None)
        if run_ai and evaluation.audio_file:
            try:
                cand_name = f"{application.first_name} {application.last_name}"
                job_title = application.job.title if application.job else "Role"
                ai_result = analyze_interview_audio(
                    audio_path=evaluation.audio_file.path,
                    candidate_name=cand_name,
                    job_title=job_title,
                    interviewer_notes=evaluation.general_notes,
                )
                evaluation.ai_audio_transcript = ai_result.get("transcript", "")
                evaluation.ai_audio_summary = ai_result.get("summary", "")
                evaluation.ai_audio_score = int(ai_result.get("score", 75))
                evaluation.ai_audio_insights = {
                    "key_points": ai_result.get("key_points", []),
                    "red_flags": ai_result.get("red_flags", []),
                    "ai_recommendation": ai_result.get("recommendation", "Hire"),
                }
                evaluation.save()
            except Exception as ai_err:
                import logging
                logging.getLogger(__name__).warning("Candidate evaluation AI audio analysis failed: %s", ai_err)

        # Move candidate to Evaluation stage if in Screening, Shortlisted, or Interview stage
        if application.status in ["Screening", "Shortlisted", "Interview"]:
            application.status = "Evaluation"
            application.save(update_fields=["status"])

        # Update interview session status:
        # If all applicants in the session have completed evaluations, session is Completed.
        # Otherwise, session is Ongoing.
        interview = evaluation.interview or application.interview.order_by("-date", "-time").first()
        if interview:
            all_apps = list(interview.applicants.all())
            all_completed = all(
                hasattr(a, "evaluation") and a.evaluation and a.evaluation.status == "Completed"
                for a in all_apps
            ) if all_apps else True
            if all_completed:
                interview.status = "Completed"
            else:
                interview.status = "Ongoing"
            interview.save(update_fields=["status"])

        invalidate_hr_cache()

        log_hr_action(
            request,
            action="EVALUATION_COMPLETED",
            target_repr=f"{application.first_name} {application.last_name} (#{application.application_id})",
            details=f"Completed evaluation: Rating {evaluation.overall_rating}/5.0, Mode: {evaluation.interview_mode}, Recommendation: '{evaluation.recommendation}'.",
            target_model="CandidateEvaluation",
            target_id=evaluation.pk,
        )

        messages.success(
            request,
            f"Candidate evaluation for {application.first_name} {application.last_name} has been saved successfully."
        )

        redirect_to = request.POST.get("redirect_to")
        if redirect_to == "reports":
            return redirect("reports")
        if redirect_to == "interviews":
            return redirect("interviews")

        return redirect(f"{reverse('candidate_detail', kwargs={'pk': pk})}#candidate-evaluation-section")

    return redirect("candidate_detail", pk=pk)


@never_cache
@hr_required(login_url="hr_login")
def start_candidate_evaluation(request, pk):
    """
    Called when HR initiates evaluation on an applicant.
    Creates or sets a Draft evaluation for this specific candidate (Ongoing).
    Also sets the shared interview session status to Ongoing.
    """
    application = get_object_or_404(Application, pk=pk)
    interview = application.interview.order_by("-date", "-time").first()

    # 1. Candidate-specific evaluation state
    evaluation, created = CandidateEvaluation.objects.get_or_create(
        application=application,
        defaults={
            "status": "Draft",
            "interview": interview,
        }
    )
    if not created and evaluation.status != "Completed":
        evaluation.status = "Draft"
        if not evaluation.interview and interview:
            evaluation.interview = interview
        evaluation.save(update_fields=["status", "interview"] if not evaluation.interview else ["status"])

    # 2. Update session status to Ongoing if it was Scheduled or Rescheduled
    if interview and interview.status in ("Scheduled", "Rescheduled"):
        interview.status = "Ongoing"
        interview.save(update_fields=["status"])

    invalidate_hr_cache()

    accept_hdr = request.headers.get("accept", "")
    is_ajax = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or request.GET.get("format") == "json"
        or request.content_type == "application/json"
        or ("application/json" in accept_hdr and "text/html" not in accept_hdr)
    )

    if is_ajax:
        return JsonResponse({
            "success": True,
            "status": "Ongoing",
            "applicant_id": application.id,
            "message": "Candidate evaluation set to Ongoing."
        })

    return redirect(f"{reverse('candidate_detail', kwargs={'pk': pk})}?evaluate=1#candidate-evaluation-section")


@never_cache
@hr_required(login_url="hr_login")
def cancel_candidate_evaluation(request, pk):
    """
    Called when HR cancels the candidate evaluation modal without saving.
    Reverts this candidate's Draft evaluation, making them Scheduled again.
    If no other candidate in the session has an active evaluation, reverts session to Scheduled or Rescheduled.
    """
    application = get_object_or_404(Application, pk=pk)
    # 1. Delete Draft evaluation for this candidate so they become Scheduled
    if hasattr(application, "evaluation") and application.evaluation and application.evaluation.status == "Draft":
        application.evaluation.delete()

    # 2. Check if the shared interview session still has any remaining evaluations
    interview = application.interview.order_by("-date", "-time").first()
    if interview:
        has_active_evals = CandidateEvaluation.objects.filter(interview=interview).exists()
        if not has_active_evals and interview.status == "Ongoing":
            if interview.notes and "[Rescheduled on" in interview.notes:
                interview.status = "Rescheduled"
            else:
                interview.status = "Scheduled"
            interview.save(update_fields=["status"])

    invalidate_hr_cache()

    accept_hdr = request.headers.get("accept", "")
    is_ajax = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or request.GET.get("format") == "json"
        or request.content_type == "application/json"
        or ("application/json" in accept_hdr and "text/html" not in accept_hdr)
    )

    if is_ajax:
        return JsonResponse({
            "success": True,
            "status": "Scheduled",
            "applicant_id": application.id,
            "message": "Candidate evaluation reverted to Scheduled."
        })

    return redirect("interviews")


def build_final_decision_department_sections(decision_type, filter_dept=None, filter_search=None):
    """
    Builds department-and-job grouped hierarchy for candidates with final decisions (Hired or Not Hired).
    Follows the exact layout specification of Candidate Management (/hr/candidates/).
    """
    if decision_type == "Hired":
        qs = Application.objects.filter(
            Q(evaluation__final_decision="Hired") | (Q(status="Hired") & Q(evaluation__final_decision__isnull=True))
        )
    else:
        qs = Application.objects.filter(evaluation__final_decision="Not Hired")

    qs = qs.select_related(
        "job", "applicant", "evaluation", "evaluation__final_decision_by"
    ).order_by("-evaluation__final_decision_date", "-evaluation__updated_at")

    if filter_dept:
        qs = qs.filter(job__department=filter_dept)

    if filter_search:
        qs = qs.filter(
            Q(first_name__icontains=filter_search)
            | Q(last_name__icontains=filter_search)
            | Q(application_id__icontains=filter_search)
            | Q(email__icontains=filter_search)
            | Q(job__title__icontains=filter_search)
            | Q(evaluation__final_decision_notes__icontains=filter_search)
        )

    apps = list(qs)

    dept_map = defaultdict(lambda: defaultdict(list))
    all_jobs_per_dept = defaultdict(dict)

    for app in apps:
        d_name = app.job.department.strip() if app.job.department else "General"
        j_id = app.job.id
        j_title = app.job.title
        all_jobs_per_dept[d_name][j_id] = j_title
        dept_map[d_name][app.job].append(app)

    department_sections = []
    for d_name in sorted(dept_map.keys()):
        jobs_in_dept = []
        for job_obj, cand_list in dept_map[d_name].items():
            jobs_in_dept.append({
                "job": job_obj,
                "candidates": cand_list,
                "candidate_count": len(cand_list),
            })

        all_dept_jobs = [
            {"id": j_id, "title": title}
            for j_id, title in all_jobs_per_dept[d_name].items()
        ]

        department_sections.append({
            "name": d_name,
            "jobs": jobs_in_dept,
            "all_jobs": all_dept_jobs,
            "job_count": len(jobs_in_dept),
            "total_candidates": sum(len(c["candidates"]) for c in jobs_in_dept),
        })

    return department_sections


@hr_required(login_url="hr_login")
def final_review_modal(request, pk):
    """
    Renders the Final Review modal partial for an applicant.
    Allows HR to view applicant profile, rubric scores, evaluator notes,
    and make the final hiring determination (Hired or Not Hired + note).
    """
    application = get_object_or_404(
        Application.objects.select_related("job", "applicant").prefetch_related("interview"),
        pk=pk
    )
    evaluation = getattr(application, "evaluation", None)
    if evaluation is None:
        try:
            evaluation = CandidateEvaluation.objects.filter(application=application).first()
        except Exception:
            evaluation = None

    interview_session = InterviewSession.objects.filter(application=application).first()
    last_interview = application.interview.order_by("-date", "-time").first()

    context = {
        "application": application,
        "evaluation": evaluation,
        "interview_session": interview_session,
        "last_interview": last_interview,
    }
    return render(request, "hr/partials/final_review_modal.html", context)


@hr_required(login_url="hr_login")
def finalize_candidate_decision(request, pk):
    """
    Processes the final hiring decision submission from HR.
    Sets CandidateEvaluation.final_decision to 'Hired' or 'Not Hired'.
    Enforces a mandatory note when 'Not Hired' is chosen.
    Updates Application.status to 'Hired' or 'Rejected'.
    Logs the action in AuditLog.
    """
    if request.method != "POST":
        return redirect("reports")

    application = get_object_or_404(Application.objects.select_related("job"), pk=pk)
    decision = request.POST.get("decision", "").strip()
    final_notes = request.POST.get("final_notes", "").strip()

    if decision not in ["Hired", "Not Hired"]:
        messages.error(request, "Please choose a valid final decision: Hired or Not Hired.")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "Invalid decision"}, status=400)
        return redirect(reverse("reports") + "?tab=evaluations")

    if decision == "Not Hired" and not final_notes:
        messages.error(request, "A reason explaining why the candidate was not hired is required.")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "Reason note is required when marking candidate as Not Hired."}, status=400)
        return redirect(reverse("reports") + "?tab=evaluations")

    # Update or create evaluation
    evaluation, _ = CandidateEvaluation.objects.get_or_create(application=application)
    evaluation.final_decision = decision
    evaluation.final_decision_notes = final_notes
    evaluation.final_decision_date = timezone.now()
    evaluation.final_decision_by = request.user
    evaluation.save()

    # Update application status
    new_status = "Hired" if decision == "Hired" else "Rejected"
    application.status = new_status
    application.save(update_fields=["status"])

    # Log HR Action strictly for applicant management
    action_key = "FINAL_DECISION_HIRED" if decision == "Hired" else "FINAL_DECISION_NOT_HIRED"
    log_hr_action(
        request,
        action=action_key,
        target_model="Application",
        target_id=str(application.id),
        target_repr=f"{application.first_name} {application.last_name} ({application.application_id})",
        details=f"Final Decision finalized as '{decision}' for {application.job.title}. Notes: {final_notes or 'None'}"
    )

    invalidate_hr_cache()

    msg = f"Final decision '{decision}' recorded successfully for {application.first_name} {application.last_name}."
    messages.success(request, msg)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "success": True,
            "message": msg,
            "decision": decision,
            "redirect_url": reverse("reports") + "?tab=final_decision"
        })

    next_url = request.POST.get("next") or (reverse("reports") + "?tab=final_decision")
    return redirect(next_url)


@never_cache
@hr_required(login_url="hr_login")
def reports_dashboard(request):
    """
    Unified HR Reports & Compliance Hub:
    Centralized navigation for:
      1. Audit Logs (HR Applicant Actions & Activity Trail)
      2. Cancelled (Rejected Applications)
      3. Evaluated Candidates (Pending Final Decision)
      4. Candidates with Final Decision (Hired and Not Hired by Dept & Job)
    """
    seed_applicant_management_logs_if_empty()

    active_tab = request.GET.get("tab", "audit").strip().lower()
    if active_tab not in ["audit", "cancelled", "evaluations", "final_decision"]:
        active_tab = "audit"

    # ==========================================
    # 1. AUDIT LOGS DATA & METRICS (HR Actions Only)
    # ==========================================
    audit_qs = AuditLog.objects.select_related("user").all()

    audit_action = request.GET.get("audit_action", "").strip()
    audit_user = request.GET.get("audit_user", "").strip()
    audit_date_range = request.GET.get("audit_date_range", "").strip()
    audit_search = request.GET.get("audit_search", "").strip()

    if audit_action:
        audit_qs = audit_qs.filter(action=audit_action)
    if audit_user:
        audit_qs = audit_qs.filter(user_id=audit_user)
    if audit_date_range == "today":
        audit_qs = audit_qs.filter(timestamp__date=timezone.now().date())
    elif audit_date_range == "7days":
        audit_qs = audit_qs.filter(timestamp__gte=timezone.now() - timedelta(days=7))
    elif audit_date_range == "30days":
        audit_qs = audit_qs.filter(timestamp__gte=timezone.now() - timedelta(days=30))

    if audit_search:
        audit_qs = audit_qs.filter(
            Q(target_repr__icontains=audit_search)
            | Q(details__icontains=audit_search)
            | Q(user_name__icontains=audit_search)
            | Q(ip_address__icontains=audit_search)
            | Q(action_display__icontains=audit_search)
        )

    all_audit_logs = AuditLog.objects.all()
    total_audit_logs = all_audit_logs.count()
    audit_today_count = all_audit_logs.filter(timestamp__date=timezone.now().date()).count()
    audit_status_changes_count = all_audit_logs.filter(
        action__in=[
            "STATUS_CHANGE", "REJECT_APPLICATION", "SHORTLIST_APPLICATION",
            "HIRE_APPLICATION", "FINAL_DECISION_HIRED", "FINAL_DECISION_NOT_HIRED"
        ]
    ).count()
    active_staff_count = all_audit_logs.exclude(user__isnull=True).values("user").distinct().count()

    available_audit_actions = AuditLog.ACTION_CHOICES
    available_audit_users = User.objects.filter(is_staff=True).order_by("first_name", "username")

    audit_logs_list = list(audit_qs[:200])

    # ==========================================
    # 2. CANCELLED (REJECTED APPLICATIONS) DATA & METRICS
    # ==========================================
    cancelled_qs = Application.objects.filter(status="Rejected").select_related("job", "applicant").prefetch_related("interview").order_by("-created_at")

    cancelled_dept = request.GET.get("cancelled_dept", "").strip()
    cancelled_job = request.GET.get("cancelled_job", "").strip()
    cancelled_search = request.GET.get("cancelled_search", "").strip()

    if cancelled_dept:
        cancelled_qs = cancelled_qs.filter(job__department=cancelled_dept)
    if cancelled_job:
        cancelled_qs = cancelled_qs.filter(job_id=cancelled_job)
    if cancelled_search:
        cancelled_qs = cancelled_qs.filter(
            Q(first_name__icontains=cancelled_search)
            | Q(last_name__icontains=cancelled_search)
            | Q(application_id__icontains=cancelled_search)
            | Q(email__icontains=cancelled_search)
            | Q(job__title__icontains=cancelled_search)
        )

    total_applications = Application.objects.count()
    total_cancelled = Application.objects.filter(status="Rejected").count()
    rejection_rate = round((total_cancelled / total_applications * 100), 1) if total_applications > 0 else 0.0

    cancelled_applications_list = list(cancelled_qs)
    for app in cancelled_applications_list:
        last_interview = app.interview.order_by("-date", "-time").first()
        if hasattr(app, "evaluation") and app.evaluation:
            app.disqualified_stage = "Post-Evaluation"
            app.stage_badge_class = "badge-purple"
            app.disqualified_notes = app.evaluation.final_decision_notes or app.evaluation.weaknesses_notes or app.evaluation.general_notes or "Did not meet evaluation rubric benchmark."
        elif last_interview:
            app.disqualified_stage = "Interview Stage"
            app.stage_badge_class = "badge-blue"
            app.disqualified_notes = last_interview.notes or "Cancelled or disqualified during interview stage."
        else:
            app.disqualified_stage = "Screening Stage"
            app.stage_badge_class = "badge-amber"
            app.disqualified_notes = app.ai_summary or "Application not selected during resume screening."

    cancelled_screening_count = sum(1 for a in cancelled_applications_list if a.disqualified_stage == "Screening Stage")
    cancelled_interview_count = sum(1 for a in cancelled_applications_list if a.disqualified_stage in ["Interview Stage", "Post-Evaluation"])

    # ==========================================
    # 3. EVALUATED CANDIDATES (Pending Final Decision)
    # ==========================================
    # Candidates whose evaluation is completed but final decision is NOT yet finalized
    eval_qs = CandidateEvaluation.objects.filter(
        status="Completed"
    ).filter(
        Q(final_decision__isnull=True) | Q(final_decision="")
    ).select_related(
        "application__job", "evaluator", "interview"
    ).order_by("-evaluation_date", "-created_at")

    selected_department = request.GET.get("department", "").strip()
    selected_mode = request.GET.get("mode", "").strip()
    selected_recommendation = request.GET.get("recommendation", "").strip()
    search_query = request.GET.get("search", "").strip()

    if selected_department:
        eval_qs = eval_qs.filter(application__job__department=selected_department)
    if selected_mode:
        eval_qs = eval_qs.filter(interview_mode=selected_mode)
    if selected_recommendation:
        eval_qs = eval_qs.filter(recommendation=selected_recommendation)
    if search_query:
        eval_qs = eval_qs.filter(
            Q(application__first_name__icontains=search_query) |
            Q(application__last_name__icontains=search_query) |
            Q(application__application_id__icontains=search_query) |
            Q(application__job__title__icontains=search_query)
        )

    evaluations_list = list(eval_qs)

    # Calculate metrics for evaluated candidates
    all_evals = CandidateEvaluation.objects.all()
    total_evaluations = all_evals.count()
    avg_score_agg = all_evals.aggregate(avg_val=Avg("overall_rating"))
    avg_score = round(float(avg_score_agg["avg_val"] or 0), 1)

    rec_counts = all_evals.aggregate(
        strong_hire=Count("id", filter=Q(recommendation="Strong Hire")),
        hire=Count("id", filter=Q(recommendation="Hire")),
        hold=Count("id", filter=Q(recommendation="Hold")),
        no_hire=Count("id", filter=Q(recommendation="No Hire")),
        audio_analyzed=Count("id", filter=Q(ai_audio_score__gt=0)),
    )

    all_departments = sorted(list(set(
        Job.objects.exclude(department="").values_list("department", flat=True)
    )))
    all_jobs = Job.objects.all().order_by("title")

    pending_eval_candidates = list(
        Application.objects.filter(status="Interview", evaluation__isnull=True)
        .select_related("job")
        .order_by("-created_at")[:10]
    )

    # ==========================================
    # 4. CANDIDATES WITH FINAL DECISION (Hired & Not Hired by Dept & Job)
    # ==========================================
    final_dept_filter = request.GET.get("final_dept", "").strip()
    final_search_filter = request.GET.get("final_search", "").strip()

    hired_department_sections = build_final_decision_department_sections("Hired", final_dept_filter, final_search_filter)
    not_hired_department_sections = build_final_decision_department_sections("Not Hired", final_dept_filter, final_search_filter)

    total_hired_final = sum(d["total_candidates"] for d in hired_department_sections)
    total_not_hired_final = sum(d["total_candidates"] for d in not_hired_department_sections)
    total_final_decisions_count = total_hired_final + total_not_hired_final
    pending_final_decisions_count = len(evaluations_list)

    context = {
        "active_tab": active_tab,
        # Global Top Stat Cards Metrics
        "pending_final_decisions_count": pending_final_decisions_count,
        "total_final_decisions_count": total_final_decisions_count,
        "total_hired_final": total_hired_final,
        "total_not_hired_final": total_not_hired_final,
        "total_cancelled": total_cancelled,
        "rejection_rate": rejection_rate,
        "total_audit_logs": total_audit_logs,
        "audit_today_count": audit_today_count,
        # Audit Logs Context
        "audit_logs": audit_logs_list,
        "audit_status_changes_count": audit_status_changes_count,
        "active_staff_count": active_staff_count,
        "available_audit_actions": available_audit_actions,
        "available_audit_users": available_audit_users,
        "audit_action": audit_action,
        "audit_user": audit_user,
        "audit_date_range": audit_date_range,
        "audit_search": audit_search,
        # Cancelled Applications Context
        "cancelled_applications": cancelled_applications_list,
        "cancelled_screening_count": cancelled_screening_count,
        "cancelled_interview_count": cancelled_interview_count,
        "cancelled_dept": cancelled_dept,
        "cancelled_job": cancelled_job,
        "cancelled_search": cancelled_search,
        "available_jobs": all_jobs,
        # Evaluated Candidates Context
        "evaluations": evaluations_list,
        "total_evaluations": total_evaluations,
        "avg_score": avg_score,
        "strong_hire_count": rec_counts["strong_hire"] or 0,
        "hire_count": rec_counts["hire"] or 0,
        "hold_count": rec_counts["hold"] or 0,
        "no_hire_count": rec_counts["no_hire"] or 0,
        "audio_analyzed_count": rec_counts["audio_analyzed"] or 0,
        "available_departments": all_departments,
        "selected_department": selected_department,
        "selected_mode": selected_mode,
        "selected_recommendation": selected_recommendation,
        "search_query": search_query,
        "pending_eval_candidates": pending_eval_candidates,
        # Candidates with Final Decision Context
        "hired_department_sections": hired_department_sections,
        "not_hired_department_sections": not_hired_department_sections,
        "final_dept_filter": final_dept_filter,
        "final_search_filter": final_search_filter,
    }

    return render(request, "hr/reports.html", context)


