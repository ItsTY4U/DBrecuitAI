import logging
import uuid
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.signing import TimestampSigner
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse

from main.emailer import send_gmail_message
from .models import ApplicantProfile

logger = logging.getLogger(__name__)


def create_google_verification_token(user, email):
    """
    Generates a cryptographically signed verification token with a unique single-use nonce.
    Cached for 15 minutes (900 seconds).
    """
    nonce = uuid.uuid4().hex
    signer = TimestampSigner(salt="google-auth-verify")
    raw_token = f"{user.pk}:{email}:{nonce}"
    signed_token = signer.sign(raw_token)
    cache_key = f"google_auth_nonce_{user.pk}_{nonce}"
    cache.set(cache_key, email, timeout=900)
    return signed_token


def send_google_verification_email(request, user, email, token):
    """
    Constructs the approval link and dispatches the verification email to the applicant's Gmail.
    """
    verify_path = reverse("google_verify_approve", kwargs={"token": token})
    site_domain = getattr(settings, "SITE_DOMAIN", "").rstrip("/")
    host = request.get_host() if request else ""

    if not site_domain or host.startswith("localhost") or host.startswith("127.0.0.1") or getattr(settings, "DEBUG", False):
        if request:
            verify_url = request.build_absolute_uri(verify_path)
        else:
            verify_url = f"{site_domain}{verify_path}"
    else:
        verify_url = f"{site_domain}{verify_path}"

    context = {
        "applicant_name": user.get_full_name() or user.first_name or "Applicant",
        "user_email": email,
        "verify_url": verify_url,
        "expires_in_minutes": 15,
    }

    try:
        html_content = render_to_string("emails/google_verify.html", context)
        text_content = render_to_string("emails/google_verify.txt", context)
        subject = "Approve Your DBRecruitAI Sign-In Request"

        result = send_gmail_message(
            to_email=email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
        )
        return result, verify_url
    except Exception as e:
        logger.error("Failed to send Google sign-in verification email to %s: %s", email, e)
        return {"success": False, "error": str(e)}, verify_url


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        if sociallogin.account.extra_data.get("email"):
            user.email = sociallogin.account.extra_data.get("email")
            user.save(update_fields=["email"])
        ApplicantProfile.objects.get_or_create(user=user)
        return user

    def pre_social_login(self, request, sociallogin):
        """
        Intercepts Google OAuth callback:
        Does NOT log the user in immediately. Instead, dispatches an approval
        link to their Gmail and redirects them to the check-email prompt.
        """
        email = (
            sociallogin.account.extra_data.get("email")
            or getattr(sociallogin.user, "email", "")
            or ""
        ).strip().lower()

        if not email:
            return super().pre_social_login(request, sociallogin)

        # 1. Resolve or create the User and ApplicantProfile
        if sociallogin.is_existing:
            user = sociallogin.user
        else:
            existing_user = User.objects.filter(email__iexact=email).first()
            if existing_user:
                user = existing_user
                sociallogin.connect(request, user)
            else:
                first_name = (
                    sociallogin.account.extra_data.get("given_name")
                    or getattr(sociallogin.user, "first_name", "")
                    or ""
                )
                last_name = (
                    sociallogin.account.extra_data.get("family_name")
                    or getattr(sociallogin.user, "last_name", "")
                    or ""
                )
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                )
                ApplicantProfile.objects.get_or_create(user=user)
                sociallogin.connect(request, user)

        ApplicantProfile.objects.get_or_create(user=user)

        # 2. Generate a secure, time-limited verification token
        token = create_google_verification_token(user, email)

        # 3. Send approval verification link to the applicant's Gmail
        result, verify_url = send_google_verification_email(request, user, email, token)

        # 4. Store pending email & state in session for check-email UI
        request.session["pending_google_email"] = email
        request.session["pending_google_user_id"] = user.pk
        request.session["pending_google_name"] = user.get_full_name() or user.first_name or "Applicant"
        if not result.get("success") and getattr(settings, "DEBUG", False):
            request.session["pending_google_dev_verify_url"] = verify_url

        # 5. Halt immediate login and redirect to the verification prompt page
        raise ImmediateHttpResponse(redirect("google_verify_sent"))