import logging
from django.utils import timezone
from .models import AuditLog

logger = logging.getLogger(__name__)


def is_hr_user(user):
    """
    Checks if the user is authenticated and belongs to the HR staff group or is an authorized admin.
    """
    if not user or not user.is_authenticated:
        return False
    return (user.is_staff and user.groups.filter(name="HR").exists()) or user.is_superuser


def get_client_ip(request):
    """Extracts client IP address safely considering proxies."""
    if not request:
        return ""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def log_hr_action(request, action, target_repr="", details="", target_model="", target_id=None):
    """
    Safely creates an AuditLog record. Catches all exceptions so normal HR flows are never blocked.
    """
    try:
        user = getattr(request, "user", None)
        user_obj = user if (user and user.is_authenticated) else None

        user_name = "System"
        if user_obj:
            full_name = f"{user_obj.first_name} {user_obj.last_name}".strip()
            user_name = full_name or user_obj.username

        action_map = dict(AuditLog.ACTION_CHOICES)
        action_display = action_map.get(action, action.replace("_", " ").title())
        ip_addr = get_client_ip(request)

        audit_obj = AuditLog.objects.create(
            user=user_obj,
            user_name=user_name,
            action=action,
            action_display=action_display,
            target_model=target_model or "",
            target_id=str(target_id) if target_id is not None else "",
            target_repr=str(target_repr)[:255] if target_repr else "",
            details=details or "",
            ip_address=ip_addr,
            timestamp=timezone.now(),
        )

        # Trigger team notification for HR user actions
        if user_obj and action in (
            "FINAL_DECISION_HIRED", "FINAL_DECISION_NOT_HIRED",
            "HIRE_APPLICATION", "REJECT_APPLICATION", "SHORTLIST_APPLICATION",
            "INTERVIEW_SCHEDULED", "INTERVIEW_RESCHEDULED", "INTERVIEW_CANCELLED",
            "EVALUATION_COMPLETED", "JOB_CREATED", "JOB_UPDATED", "DEPARTMENT_CREATED"
        ):
            target_link = "/hr/candidates/"
            if target_model == "Application" and target_id:
                target_link = f"/hr/candidates/applicant/{target_id}/"
            elif target_model == "Interview":
                target_link = "/hr/interviews/"
            elif target_model == "Job":
                target_link = "/hr/jobs/"
            elif "FINAL_DECISION" in action:
                target_link = "/hr/reports/?tab=final_decision"
            elif action == "EVALUATION_COMPLETED":
                target_link = "/hr/reports/?tab=evaluations"

            create_hr_notification(
                notification_type="HR_ACTION",
                title=f"{action_display}: {target_repr}",
                message=f"{user_name}: {details or action_display} ({target_repr})".strip(),
                link=target_link,
                recipient=None,
            )

        return audit_obj
    except Exception as e:
        logger.warning(f"Failed to create AuditLog: {e}")
        return None


def purge_legacy_admin_logs():
    """
    Purges any legacy Django admin log entries that were previously backfilled into AuditLog.
    Keeps only genuine HR applicant management actions.
    """
    try:
        # Delete entries that were copied from Django admin logs
        AuditLog.objects.filter(details__icontains="Administrative action on").delete()
    except Exception as e:
        logger.warning(f"Failed to purge legacy admin logs: {e}")


def seed_applicant_management_logs_if_empty():
    """
    Seeds realistic HR applicant management audit logs strictly based on real
    interviews, evaluations, and candidate updates when the table is empty.
    Never pulls from django_admin_log.
    """
    try:
        purge_legacy_admin_logs()

        if AuditLog.objects.exists():
            return

        from jobs.models import Application
        from .models import Interview, CandidateEvaluation

        logs_to_create = []

        # 1. Seed interview schedule logs
        for interview in Interview.objects.prefetch_related("applicants").order_by("created_at"):
            app_names = ", ".join([f"{a.first_name} {a.last_name}" for a in interview.applicants.all()]) or "Candidates"
            logs_to_create.append(AuditLog(
                user_name="HR Recruitment Team",
                action="INTERVIEW_SCHEDULED",
                action_display="Interview Scheduled",
                target_model="Interview",
                target_id=str(interview.id),
                target_repr=f"{interview.interview_type} - {app_names}",
                details=f"Scheduled {interview.interview_type} session on {interview.date} at {interview.time.strftime('%I:%M %p')} for {app_names}.",
                ip_address="127.0.0.1",
                timestamp=interview.created_at,
            ))

        # 2. Seed candidate evaluation logs
        for evaluation in CandidateEvaluation.objects.select_related("application", "evaluator").order_by("created_at"):
            app = evaluation.application
            eval_name = evaluation.evaluator_name or (evaluation.evaluator.get_full_name() if evaluation.evaluator else "HR Staff")
            logs_to_create.append(AuditLog(
                user=evaluation.evaluator,
                user_name=eval_name,
                action="EVALUATION_COMPLETED",
                action_display="Evaluation Completed",
                target_model="CandidateEvaluation",
                target_id=str(evaluation.id),
                target_repr=f"Evaluation: {app.first_name} {app.last_name}",
                details=f"Completed {evaluation.interview_mode} evaluation for {app.first_name} {app.last_name} ({app.job.title}). Score: {evaluation.overall_rating}/5.0, Recommendation: {evaluation.recommendation}.",
                ip_address="127.0.0.1",
                timestamp=evaluation.created_at,
            ))

        # 3. Seed application status transition logs for shortlisted/rejected/hired
        for app in Application.objects.filter(status__in=["Shortlisted", "Rejected", "Hired"]).select_related("job").order_by("created_at")[:10]:
            if app.status == "Rejected":
                action_key = "REJECT_APPLICATION"
                disp = "Application Rejected"
                desc = f"Application for {app.first_name} {app.last_name} ({app.job.title}) closed and candidate disqualified."
            elif app.status == "Shortlisted":
                action_key = "SHORTLIST_APPLICATION"
                disp = "Application Shortlisted"
                desc = f"Candidate {app.first_name} {app.last_name} advanced to Shortlisted stage for {app.job.title}."
            else:
                action_key = "HIRE_APPLICATION"
                disp = "Application Hired"
                desc = f"Candidate {app.first_name} {app.last_name} officially hired for {app.job.title}."

            logs_to_create.append(AuditLog(
                user_name="HR Recruitment Team",
                action=action_key,
                action_display=disp,
                target_model="Application",
                target_id=str(app.id),
                target_repr=f"Application: {app.first_name} {app.last_name} ({app.application_id})",
                details=desc,
                ip_address="127.0.0.1",
                timestamp=app.created_at,
            ))

        if logs_to_create:
            AuditLog.objects.bulk_create(logs_to_create)
    except Exception as e:
        logger.warning(f"Failed to seed applicant management logs: {e}")


def create_hr_notification(title, message, notification_type="SYSTEM", link="", recipient=None):
    """
    Safely creates an HRNotification record.
    """
    from .models import HRNotification
    try:
        return HRNotification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title[:150],
            message=message,
            link=link[:255] if link else "",
            is_read=False,
            created_at=timezone.now(),
        )
    except Exception as e:
        logger.warning(f"Failed to create HRNotification: {e}")
        return None


def seed_initial_notifications_if_empty():
    """
    Seeds initial HR notifications from recent applications and completed video interviews if empty.
    """
    from .models import HRNotification
    from jobs.models import Application
    from video_interview.models import InterviewSession
    from django.urls import reverse

    try:
        if HRNotification.objects.exists():
            return

        notifs = []
        # Recent applications
        recent_apps = Application.objects.select_related("job").order_by("-created_at")[:10]
        for app in recent_apps:
            try:
                cand_link = reverse("candidate_detail", kwargs={"pk": app.pk})
            except Exception:
                cand_link = f"/hr/candidates/applicant/{app.pk}/"

            notifs.append(HRNotification(
                notification_type="NEW_APPLICATION",
                title=f"New Application: {app.first_name} {app.last_name}",
                message=f"Applied for {app.job.title} in {app.job.department or 'General'}",
                link=cand_link,
                is_read=False,
                created_at=app.created_at,
            ))

        # Recent completed video interview sessions
        completed_sessions = InterviewSession.objects.filter(status="COMPLETED").select_related("application", "application__job").order_by("-completed_at")[:5]
        for sess in completed_sessions:
            score_text = f" (Score: {sess.final_score}%)" if sess.final_score else ""
            try:
                sess_link = reverse("candidate_detail", kwargs={"pk": sess.application.pk})
            except Exception:
                sess_link = f"/hr/candidates/applicant/{sess.application.pk}/"

            notifs.append(HRNotification(
                notification_type="VIDEO_INTERVIEW_COMPLETED",
                title=f"Video Interview Completed: {sess.application.first_name} {sess.application.last_name}",
                message=f"Completed automated AI interview for {sess.application.job.title}{score_text}",
                link=sess_link,
                is_read=False,
                created_at=sess.completed_at or sess.created_at,
            ))

        # Recent HR team actions from AuditLog
        from .models import AuditLog
        recent_audits = AuditLog.objects.exclude(action__in=["HR_LOGIN", "HR_LOGOUT"]).order_by("-timestamp")[:6]
        for a in recent_audits:
            notifs.append(HRNotification(
                notification_type="HR_ACTION",
                title=f"{a.action_display}: {a.target_repr or a.target_model}",
                message=f"{a.user_name} performed {a.action_display.lower()} on {a.target_repr or 'record'}. {a.details}".strip(),
                link="/hr/reports/?tab=audit",
                is_read=False,
                created_at=a.timestamp,
            ))

        if notifs:
            notifs.sort(key=lambda n: n.created_at, reverse=True)
            HRNotification.objects.bulk_create(notifs)
    except Exception as e:
        logger.warning(f"Failed to seed initial HR notifications: {e}")
