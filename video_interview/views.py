import random
import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.db import close_old_connections
from django.db.models import Q

from jobs.models import Application
from .models import InterviewSession, InterviewResponse, BehavioralQuestion
from .ai import analyze_interview_session

def _run_ai_analysis_async(session_id):
    """
    Runs Gemini video interview analysis in a background daemon thread
    to keep applicant response times instantaneous.
    """
    close_old_connections()
    try:
        session = InterviewSession.objects.get(id=session_id)
        analyze_interview_session(session)
    except Exception as e:
        print(f"Error in async Gemini video interview analysis: {e}")
    finally:
        close_old_connections()

STANDARD_INTRO_QUESTIONS = [
    "Please introduce yourself and share a brief overview of your educational background and work experience.",
    "Why are you interested in this position, and what unique strengths make you a great fit for our team?",
]

DEFAULT_BEHAVIORAL_QUESTIONS = [
    "Describe a challenging project or problem you encountered at work or school. How did you approach resolving it?",
    "Tell us about a time you had to collaborate with a difficult teammate or stakeholder. How did you manage the situation?",
    "Can you share an example of when you had to adapt quickly to unexpected changes in priorities or requirements?",
    "Describe a situation where you made a mistake or failed to meet a goal. What did you learn and how did you handle it?",
    "Tell us about a time you took initiative to improve a process or solve a problem before being asked to do so.",
    "How do you prioritize your work and maintain high quality when handling multiple tight deadlines?",
]


def _get_or_create_session(application):
    session, created = InterviewSession.objects.get_or_create(
        application=application,
        defaults={"status": "PENDING"}
    )
    return session


@never_cache
@login_required(login_url="applicant_login")
def welcome_view(request, application_id):
    """
    Welcome screen for AI video interview.
    Applicant can safely exit here without penalty.
    """
    application = get_object_or_404(
        Application.objects.select_related("job", "applicant"),
        application_id=application_id
    )

    # Security check: applicant must own this application unless staff
    if not request.user.is_staff and application.applicant != request.user:
        messages.error(request, "You do not have permission to access this interview.")
        return redirect("profile")

    session = _get_or_create_session(application)

    # Check if already completed
    if session.status == "COMPLETED" and not session.can_retake:
        return render(request, "video_interview/already_taken.html", {
            "application": application,
            "session": session,
            "reason": "completed"
        })

    # Check if abandoned without retake permission
    if session.status == "ABANDONED" and not session.can_retake:
        return render(request, "video_interview/already_taken.html", {
            "application": application,
            "session": session,
            "reason": "abandoned"
        })

    return render(request, "video_interview/welcome.html", {
        "application": application,
        "session": session,
        "job": application.job,
    })


@never_cache
@login_required(login_url="applicant_login")
@require_POST
def start_interview_view(request, application_id):
    """
    Starts the interview session.
    Randomly selects 3 behavioral questions + 2 intro questions.
    Once this is called, exiting counts as abandoning.
    """
    application = get_object_or_404(Application, application_id=application_id)

    if not request.user.is_staff and application.applicant != request.user:
        return HttpResponseBadRequest("Unauthorized")

    session = _get_or_create_session(application)

    if session.is_locked:
        messages.error(request, "This interview has already been completed or abandoned.")
        return redirect("profile")

    # If retaking or previously started, clear old responses and delete their video clips from storage
    for old_resp in session.responses.all():
        old_resp.delete()

    # 1. Two standard intro questions
    questions = [
        {"number": 1, "type": "INTRO", "text": STANDARD_INTRO_QUESTIONS[0]},
        {"number": 2, "type": "INTRO", "text": STANDARD_INTRO_QUESTIONS[1]},
    ]

    # 2. Select 3 behavioral questions in a single query
    pool = list(
        BehavioralQuestion.objects.filter(
            Q(job_id=application.job_id) | Q(job__isnull=True),
            is_active=True
        )
    )
    selected_texts = []

    if pool:
        # Sample up to 3 distinct questions from pool
        sample_k = min(3, len(pool))
        chosen = random.sample(pool, sample_k)
        selected_texts = [q.question_text for q in chosen]

    # If fewer than 3, backfill from DEFAULT_BEHAVIORAL_QUESTIONS
    backfill_pool = [q for q in DEFAULT_BEHAVIORAL_QUESTIONS if q not in selected_texts]
    while len(selected_texts) < 3 and backfill_pool:
        picked = random.choice(backfill_pool)
        selected_texts.append(picked)
        backfill_pool.remove(picked)

    for idx, text in enumerate(selected_texts[:3], start=3):
        questions.append({"number": idx, "type": "BEHAVIORAL", "text": text})

    # Create InterviewResponse records in a single bulk INSERT
    InterviewResponse.objects.bulk_create([
        InterviewResponse(
            session=session,
            question_number=q["number"],
            question_type=q["type"],
            question_text=q["text"]
        )
        for q in questions
    ])

    # Set session to IN_PROGRESS
    session.status = "IN_PROGRESS"
    session.started_at = timezone.now()
    session.can_retake = False
    session.save(update_fields=["status", "started_at", "can_retake"])

    return redirect("video_interview:room", application_id=application.application_id)


@never_cache
@login_required(login_url="applicant_login")
def interview_room_view(request, application_id):
    """
    The active video interview room where applicant answers the 5 questions.
    """
    application = get_object_or_404(
        Application.objects.select_related("job"),
        application_id=application_id
    )

    if not request.user.is_staff and application.applicant != request.user:
        return redirect("profile")

    session = _get_or_create_session(application)

    if session.status != "IN_PROGRESS":
        if session.status == "COMPLETED":
            return redirect("video_interview:congratulations", application_id=application.application_id)
        return redirect("video_interview:welcome", application_id=application.application_id)

    responses = session.responses.all().order_by("question_number")
    if not responses.exists():
        # Fallback if no questions were generated
        return redirect("video_interview:welcome", application_id=application.application_id)

    questions_data = [
        {
            "number": r.question_number,
            "type": r.get_question_type_display(),
            "text": r.question_text,
        }
        for r in responses
    ]

    return render(request, "video_interview/room.html", {
        "application": application,
        "session": session,
        "job": application.job,
        "questions_data": questions_data,
        "total_questions": len(questions_data),
    })


@never_cache
@login_required(login_url="applicant_login")
@require_POST
def submit_answer_api(request, application_id):
    """
    AJAX endpoint to receive video clip recording for a specific question.
    """
    application = get_object_or_404(Application, application_id=application_id)
    if not request.user.is_staff and application.applicant != request.user:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    session = _get_or_create_session(application)
    if session.status != "IN_PROGRESS":
        return JsonResponse({"error": "Session is not active"}, status=400)

    try:
        question_number = int(request.POST.get("question_number", 1))
        skipped = request.POST.get("skipped", "false").lower() == "true"
        duration_seconds = int(request.POST.get("duration_seconds", 0))

        response = get_object_or_404(
            InterviewResponse,
            session=session,
            question_number=question_number
        )

        response.skipped = skipped
        response.duration_seconds = duration_seconds

        video_file = request.FILES.get("video")
        if video_file and not skipped:
            # Generate custom filename
            ext = ".webm"
            if video_file.name and "." in video_file.name:
                ext = "." + video_file.name.split(".")[-1]
            filename = f"{application.application_id}_q{question_number}{ext}"
            video_file.name = filename
            response.video_clip = video_file

        response.save()

        return JsonResponse({
            "success": True,
            "question_number": question_number,
            "skipped": skipped
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


from django.conf import settings

@never_cache
@login_required(login_url="applicant_login")
def finish_interview_view(request, application_id):
    """
    Marks the interview session as completed and triggers Gemini AI analysis.
    In production, this runs asynchronously in the background so applicant response is instant.
    """
    application = get_object_or_404(Application, application_id=application_id)
    if not request.user.is_staff and application.applicant != request.user:
        return redirect("profile")

    session = _get_or_create_session(application)

    if session.status == "IN_PROGRESS":
        session.status = "COMPLETED"
        session.completed_at = timezone.now()
        session.save(update_fields=["status", "completed_at"])

        # Run AI analysis in background unless synchronous mode is explicitly configured (e.g. testing)
        if getattr(settings, "ASYNC_VIDEO_ANALYSIS", True):
            threading.Thread(
                target=_run_ai_analysis_async,
                args=(session.id,),
                daemon=True
            ).start()
        else:
            try:
                analyze_interview_session(session)
            except Exception as e:
                print(f"Error in Gemini video interview analysis: {e}")

    return redirect("video_interview:congratulations", application_id=application.application_id)



@never_cache
@login_required(login_url="applicant_login")
@require_POST
def leave_interview_view(request, application_id):
    """
    Applicant leaves while answering questions.
    Session is marked ABANDONED (no retake allowed without HR intervention).
    """
    application = get_object_or_404(Application, application_id=application_id)
    if not request.user.is_staff and application.applicant != request.user:
        return redirect("profile")

    session = _get_or_create_session(application)
    if session.status == "IN_PROGRESS":
        session.status = "ABANDONED"
        session.save()

    messages.warning(
        request,
        "You exited the video interview before completing it. You cannot retake this interview unless a technical issue is verified by HR."
    )
    return redirect("profile")


@never_cache
@login_required(login_url="applicant_login")
def congratulations_view(request, application_id):
    """
    End screen after finishing the video interview.
    """
    application = get_object_or_404(
        Application.objects.select_related("job"),
        application_id=application_id
    )
    session = _get_or_create_session(application)

    return render(request, "video_interview/congratulations.html", {
        "application": application,
        "session": session,
        "job": application.job,
    })

