import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile(response_token: str, remote_ip: str = None) -> tuple[bool, str]:
    """
    Verifies a Cloudflare Turnstile response token with Cloudflare's API.
    Returns (is_valid, error_message).
    """
    secret_key = getattr(settings, "CLOUDFLARE_TURNSTILE_SECRET_KEY", "")

    # If testing dummy secret key is configured and no token provided during offline automated tests
    if not secret_key:
        logger.warning("Cloudflare Turnstile secret key is not configured; skipping verification.")
        return True, ""

    if not response_token or not response_token.strip():
        return False, "Please complete the Cloudflare security verification to continue."

    # Cloudflare test dummy keys allow bypassing or testing without external calls if needed
    if secret_key == "1x0000000000000000000000000000000AA" and response_token == "XXXX.DUMMY.TOKEN.XXXX":
        return True, ""

    data = {
        "secret": secret_key,
        "response": response_token.strip(),
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        resp = requests.post(TURNSTILE_VERIFY_URL, data=data, timeout=8)
        result = resp.json()
        if result.get("success"):
            return True, ""
        
        error_codes = result.get("error-codes", [])
        logger.warning("Cloudflare Turnstile verification failed: %s", error_codes)
        return False, "Security verification failed. Please try the checkbox again."
    except requests.RequestException as e:
        logger.error("Error communicating with Cloudflare Turnstile API: %s", e)
        # In case of network failure during presentation/local test with test key, allow graceful fallback
        if secret_key.startswith("1x0000000000000000"):
            return True, ""
        return False, "Security verification service temporarily unreachable. Please try again."
