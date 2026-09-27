import logging
from django.db.models import Q
from django.utils import timezone
from .models import HRNotification
from .utils import is_hr_user, seed_initial_notifications_if_empty

logger = logging.getLogger(__name__)


def hr_notifications_context(request):
    """
    Context processor that supplies HR notifications, unread count, and user greeting
    across all HR dashboard views and templates, isolated per logged-in HR staff user.
    """
    if not request.user.is_authenticated:
        return {}

    # Only supply context for HR staff, staff, or superusers
    if not (is_hr_user(request.user) or request.user.is_staff or request.user.is_superuser):
        return {}

    try:
        seed_initial_notifications_if_empty()
        user = request.user
        unread_count = HRNotification.objects.filter(
            Q(recipient=user) | Q(recipient__isnull=True)
        ).exclude(read_by=user).count()
        recent_notifications = list(
            HRNotification.objects.filter(
                Q(recipient=user) | Q(recipient__isnull=True)
            ).order_by("-created_at")[:15]
        )
        read_ids = set(user.read_hr_notifications.values_list("id", flat=True))
        for notif in recent_notifications:
            notif.is_read = (notif.id in read_ids)

        full_name = f"{user.first_name} {user.last_name}".strip()
        hr_user_name = full_name or user.first_name or user.username

        return {
            "unread_notifs_count": unread_count,
            "recent_notifications": recent_notifications,
            "hr_user_name": hr_user_name,
        }
    except Exception as e:
        logger.warning(f"Error in hr_notifications_context: {e}")
        return {
            "unread_notifs_count": 0,
            "recent_notifications": [],
            "hr_user_name": request.user.first_name or request.user.username,
        }
