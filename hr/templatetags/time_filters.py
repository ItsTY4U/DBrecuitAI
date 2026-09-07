from datetime import timedelta

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def smart_time(value):
    if not value:
        return ""

    now = timezone.now()

    if timezone.is_naive(value):
        value = timezone.make_aware(value)

    difference = now - value

    # Future timestamp
    if difference.total_seconds() < 0:
        return "Just now"

    seconds = difference.total_seconds()

    # Less than 1 minute
    if seconds < 60:
        return "Just now"

    # Minutes
    minutes = int(seconds // 60)

    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

    # Hours
    hours = int(minutes // 60)

    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    # Yesterday
    if value.date() == (now - timedelta(days=1)).date():
        return "Yesterday"

    # Days
    days = difference.days

    if days < 7:
        return f"{days} day{'s' if days != 1 else ''} ago"

    # Weeks
    weeks = days // 7

    if weeks < 4:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"

    # Older dates
    return f"{value.strftime('%B')} {value.day}, {value.year}"