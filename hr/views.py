from django.shortcuts import render, redirect, get_object_or_404
from jobs.models import Application, Job, Requirement, Department
from .models import Interview, CandidateEvaluation
from video_interview.models import InterviewSession, InterviewResponse
from .evaluation_ai import analyze_interview_audio
from django.db.models import Q, Count, Prefetch, F, Window, Avg
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

        recent_applications = list(
            Application.objects.select_related("job")
            .only("id", "first_name", "last_name", "email", "status", "created_at", "job__id", "job__title")
            .order_by("-created_at")[:5]
        )

        content = {
            "total_applications": total_applications,
            "screening": screening,
            "hired": hired,
            "interview": interview,
            "evaluation": evaluation,
            "active_jobs": active_jobs,
            "recent_applications": recent_applications,
            "pending_count": pending_count,
            "interview_count": interview_count,
            "screening_percent": screening_percent,
            "interview_percent": interview_percent,
            "evaluation_percent": evaluation_percent,
            "hired_percent": hired_percent,
        }
        cache.set(cache_key, content, 15)
    return render(request, "hr/dashboard.html", content)

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
            Department.objects.get_or_create(name=dept_name)
            invalidate_hr_cache()

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
            .order_by("-ai_score", "-created_at")
        )
        total_matching = search_qs.count()
        total_pages = max(1, math.ceil(total_matching / TABLE_PAGE_SIZE)) if total_matching > 0 else 1
        page_number = min(page_number, total_pages)

        offset = (page_number - 1) * TABLE_PAGE_SIZE
        candidates_page = list(search_qs[offset : offset + TABLE_PAGE_SIZE])

        for idx, cand in enumerate(candidates_page):
            cand.table_rank = offset + idx + 1

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
            .order_by("-ai_score", "-created_at")[offset : offset + TABLE_PAGE_SIZE]
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

    # Single aggregate query for all candidate status counts
    counts = Application.objects.aggregate(
        total=Count("id"),
        screening=Count("id", filter=Q(status="Screening")),
        interview=Count("id", filter=Q(status="Interview")),
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
                    order_by=[F("ai_score").desc(), F("created_at").desc()]
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
                    order_by=[F("ai_score").desc(), F("created_at").desc()]
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
    
    return render(request, "hr/candidate_detail.html", {
        "application": application,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "interview_session": interview_session,
        "interview_responses": interview_responses,
        "candidate_evaluation": candidate_evaluation,
        "scheduled_interviews": scheduled_interviews,
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
        application.status = request.POST.get("status")
        application.save()
        invalidate_hr_cache()
        
    return redirect(request.META.get("HTTP_REFERER", "candidates"))


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
        scheduled=Count("id", filter=Q(status="Scheduled")),
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
            Q(date__lt=today, status__in=["Scheduled", "Ongoing"])
        )
        .prefetch_related("applicants__job")
        .order_by("date", "time")
    )

    todays_schedule = [i for i in all_interviews if i.date == today]
    todays_schedule.sort(key=lambda x: x.time)

    upcoming_interviews = [i for i in all_interviews if today < i.date <= three_days]
    overdue_interviews = [i for i in all_interviews if i.date < today and i.status in ("Scheduled", "Ongoing")]

    # 3. Prefetch waiting applicants into `waiting_applicants` attribute on each job
    jobs = list(Job.objects.filter(status="Active").prefetch_related(
        Prefetch(
            "application",
            queryset=Application.objects.filter(
                status="Interview",
                interview__isnull=True
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
        status__in=["Screening", "Interview", "Pending"],
        interview__isnull=True,
    ).order_by("-ai_score")
    
    hr_staff = User.objects.filter(
        groups__name="HR",
        is_active=True
        ).order_by("first_name", "last_name")

    preselected_applicant_id = None
    raw_app_id = request.GET.get("applicant_id")
    if raw_app_id:
        try:
            preselected_applicant_id = int(raw_app_id)
        except (ValueError, TypeError):
            preselected_applicant_id = None

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
        # Automatically move scheduled applicants to Interview stage
        if ids:
            Application.objects.filter(id__in=ids).update(
                status="Interview",
                interview_scheduled=True
            )
        invalidate_hr_cache()

        return redirect("interviews")

    return render(
        request,
        "hr/schedule_interview.html",
        {
            "job": job,
            "applicants": applicants,
            "interview": Interview,
            "hr_staff": hr_staff,
            "preselected_applicant_id": preselected_applicant_id,
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
        invalidate_hr_cache()

    return redirect(
        "interview_detail",
        pk=interview.id
    )


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

        # Move candidate to Evaluation stage if in Screening or Interview stage
        if application.status in ["Screening", "Interview"]:
            application.status = "Evaluation"
            application.save(update_fields=["status"])

        invalidate_hr_cache()
        messages.success(
            request,
            f"Candidate evaluation for {application.first_name} {application.last_name} has been saved successfully."
        )

        redirect_to = request.POST.get("redirect_to")
        if redirect_to == "reports":
            return redirect("reports")

        return redirect(f"{reverse('candidate_detail', kwargs={'pk': pk})}#candidate-evaluation-section")

    return redirect("candidate_detail", pk=pk)


@never_cache
@hr_required(login_url="hr_login")
def reports_dashboard(request):
    """
    Reports Dashboard:
    Centralized hub for all candidate interview evaluations across Face-to-Face,
    Online, and Phone Call modes. Displays summary KPI statistics, filters,
    and detailed candidate evaluation records.
    """
    eval_qs = CandidateEvaluation.objects.select_related(
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

    # Calculate overall metrics
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

    # Candidates currently in Interview stage who are pending evaluation
    pending_eval_candidates = list(
        Application.objects.filter(status="Interview", evaluation__isnull=True)
        .select_related("job")
        .order_by("-created_at")[:10]
    )

    context = {
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
    }

    return render(request, "hr/reports.html", context)

