import time
from django.conf import settings
from django.core.cache import cache


def get_client_ip(request):
    """
    Safely extracts the client IP address accounting for reverse proxies (e.g. Vercel, Cloudflare).
    """
    cf_connecting_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_connecting_ip:
        return cf_connecting_ip.strip()

    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def check_rate_limit(
    request,
    action_key: str,
    limit: int = 3,
    window_seconds: int = 3600,
    account_identifier: str = None,
    enable_debounce: bool = True,
    debounce_seconds: int = 3,
) -> tuple[bool, str]:
    """
    Checks whether a request exceeds the maximum allowed attempts within window_seconds
    for both the client's IP address and their account.

    Also applies rapid-fire debounce protection to stop automated burst submissions.

    Returns:
        (is_limited: bool, error_message: str)
    """
    # Bypass all rate limiting and debounce while DEBUG = True to speed up development & testing
    if getattr(settings, "DEBUG", False):
        return False, ""

    ip = get_client_ip(request)

    # Resolve account identifier
    acc_id = None
    if getattr(request, "user", None) and request.user.is_authenticated:
        acc_id = f"user_{request.user.id}"
    elif account_identifier and str(account_identifier).strip():
        acc_id = f"acc_{str(account_identifier).strip().lower()}"
    elif request.method == "POST" and request.POST.get("email"):
        acc_id = f"email_{request.POST.get('email').strip().lower()}"

    # Rapid-fire debounce check (stops clicking or burst scripts within 3 seconds)
    if enable_debounce:
        ip_deb_key = f"rl:deb:{action_key}:ip:{ip}"
        acc_deb_key = f"rl:deb:{action_key}:acc:{acc_id}" if acc_id else None

        if cache.get(ip_deb_key) or (acc_deb_key and cache.get(acc_deb_key)):
            return True, "You are submitting too fast. Please wait a few seconds before trying again."

    # Hourly rate limit keys
    ip_key = f"rl:{action_key}:ip:{ip}"
    acc_key = f"rl:{action_key}:acc:{acc_id}" if acc_id else None

    ip_count = cache.get(ip_key, 0)
    acc_count = cache.get(acc_key, 0) if acc_key else 0

    if ip_count >= limit or acc_count >= limit:
        return (
            True,
            f"Rate limit exceeded: You can only perform this action {limit} times per hour. Please try again later.",
        )

    # Set debounce cooldown
    if enable_debounce:
        cache.set(ip_deb_key, 1, timeout=debounce_seconds)
        if acc_key:
            cache.set(acc_deb_key, 1, timeout=debounce_seconds)

    # Increment IP count
    try:
        if ip_count == 0:
            cache.set(ip_key, 1, timeout=window_seconds)
        else:
            cache.incr(ip_key)
    except Exception:
        cache.set(ip_key, ip_count + 1, timeout=window_seconds)

    # Increment Account count
    if acc_key:
        try:
            if acc_count == 0:
                cache.set(acc_key, 1, timeout=window_seconds)
            else:
                cache.incr(acc_key)
        except Exception:
            cache.set(acc_key, acc_count + 1, timeout=window_seconds)

    return False, ""


def is_rate_limited(request, action_key, max_requests=3, window_seconds=3600, account_identifier=None):
    """
    Convenience wrapper returning a boolean indicating if the action is rate limited.
    """
    limited, _ = check_rate_limit(
        request,
        action_key,
        limit=max_requests,
        window_seconds=window_seconds,
        account_identifier=account_identifier,
    )
    return limited
