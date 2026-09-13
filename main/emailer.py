import base64
import logging
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_gmail_credentials():
    """
    Returns valid Google OAuth2 credentials using refresh token, or None if credentials are not configured.
    """
    client_id = getattr(settings, "GMAIL_CLIENT_ID", "")
    client_secret = getattr(settings, "GMAIL_CLIENT_SECRET", "")
    refresh_token = getattr(settings, "GMAIL_REFRESH_TOKEN", "")

    if not (client_id and client_secret and refresh_token):
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        creds.refresh(Request())
        return creds
    except Exception as e:
        logger.error("Failed to refresh Gmail API OAuth2 credentials: %s", e)
        return None


def send_gmail_message(to_email: str, subject: str, html_content: str, text_content: str = None) -> dict:
    """
    Sends an email using the Gmail REST API (users.messages.send).
    Requires GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN in settings/.env.
    """
    if not to_email:
        return {"success": False, "error": "Missing recipient email"}

    creds = get_gmail_credentials()
    if not creds:
        logger.warning(
            "[Gmail Emailer] Gmail API credentials not configured or failed to refresh. "
            "Skipping email to %s (Subject: %s).",
            to_email,
            subject,
        )
        return {"success": False, "error": "Gmail API credentials not configured"}

    sender_email = getattr(settings, "GMAIL_SENDER_EMAIL", "DBRecruitAI <noreply@dbrecruitai.com>")

    try:
        # Build MIME multipart message
        message = MIMEMultipart("alternative")
        message["to"] = to_email
        message["from"] = sender_email
        message["subject"] = subject

        if text_content:
            part1 = MIMEText(text_content, "plain", "utf-8")
            message.attach(part1)

        part2 = MIMEText(html_content, "html", "utf-8")
        message.attach(part2)

        # Base64url encode the raw message per Gmail API specification
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        import requests

        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json={"raw": raw_message}, timeout=10)

        if response.status_code in (200, 201):
            data = response.json()
            logger.info("Gmail sent successfully to %s. Message ID: %s", to_email, data.get("id"))
            return {"success": True, "message_id": data.get("id")}
        else:
            logger.error(
                "Gmail API send failed [%s]: %s",
                response.status_code,
                response.text,
            )
            return {"success": False, "error": response.text, "status_code": response.status_code}

    except Exception as e:
        logger.error("Exception occurred while sending email via Gmail API: %s", e)
        return {"success": False, "error": str(e)}


def send_application_submitted_email(application, async_send: bool = True) -> bool:
    """
    Sends a confirmation email to the applicant ONLY when their job application is
    successfully submitted. This is the sole trigger currently authorized.
    """
    recipient_email = application.email
    if not recipient_email and application.applicant:
        recipient_email = application.applicant.email

    if not recipient_email:
        logger.warning(
            "Cannot send application submitted email: no email found for application %s",
            application.application_id,
        )
        return False

    applicant_name = (
        f"{application.first_name} {application.last_name}".strip()
        or (application.applicant.get_full_name() if application.applicant else "")
        or "Applicant"
    )

    site_domain = getattr(settings, "SITE_DOMAIN", "http://127.0.0.1:8000").rstrip("/")
    tracking_url = f"{site_domain}/track/?application_id={application.application_id}"

    submission_dt = application.created_at or timezone.now()
    submitted_at_str = submission_dt.strftime("%B %d, %Y at %I:%M %p")

    context = {
        "application": application,
        "job": application.job,
        "applicant_name": applicant_name,
        "tracking_url": tracking_url,
        "submitted_at": submitted_at_str,
    }

    subject = f"Application Received: {application.job.title} - Ref #{application.application_id}"

    try:
        html_content = render_to_string("emails/application_submitted.html", context)
        text_content = render_to_string("emails/application_submitted.txt", context)
    except Exception as e:
        logger.error("Failed to render application submitted email templates: %s", e)
        return False

    def _worker():
        try:
            send_gmail_message(
                to_email=recipient_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )
        except Exception as exc:
            logger.error("Error in background Gmail worker: %s", exc)

    if async_send:
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return True
    else:
        result = send_gmail_message(
            to_email=recipient_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
        )
        return result.get("success", False)
