from django.core.cache import cache


def get_client_ip(request):
    """Safely extracts client IP address accounting for proxies (e.g. Vercel, Cloudflare)."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def is_rate_limited(request, action_key, max_requests=10, window_seconds=60):
    """
    Checks if client IP has exceeded max_requests in window_seconds.
    Returns True if rate limit is exceeded, False otherwise.
    """
    ip = get_client_ip(request)
    cache_key = f"rl:{action_key}:{ip}"

    count = cache.get(cache_key, 0)
    if count >= max_requests:
        return True

    try:
        if count == 0:
            cache.set(cache_key, 1, timeout=window_seconds)
        else:
            cache.incr(cache_key)
    except Exception:
        cache.set(cache_key, count + 1, timeout=window_seconds)

    return False
