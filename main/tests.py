from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from jobs.models import Job, Application
from main.emailer import (
    send_application_submitted_email,
    send_gmail_message,
    get_gmail_credentials,
)


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class GmailEmailerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="candidate1",
            first_name="Jane",
            last_name="Doe",
            email="candidate@example.com"
        )
        self.job = Job.objects.create(
            title="Senior Python Engineer",
            department="Engineering",
            job_type="FULL-TIME",
            status="Active"
        )
        self.application = Application.objects.create(
            application_id="APP998877",
            applicant=self.user,
            job=self.job,
            first_name="Jane",
            last_name="Doe",
            email="candidate@example.com",
            phone="09123456789",
            status="Pending"
        )

    def test_email_templates_render_successfully(self):
        """Verify HTML and plain-text templates render with expected application context."""
        context = {
            "application": self.application,
            "job": self.job,
            "applicant_name": "Jane Doe",
            "tracking_url": "http://127.0.0.1:8000/accounts/profile/",
            "profile_url": "http://127.0.0.1:8000/accounts/profile/",
            "submitted_at": "September 13, 2026 at 09:30 PM",
        }
        html_out = render_to_string("emails/application_submitted.html", context)
        text_out = render_to_string("emails/application_submitted.txt", context)

        self.assertIn("Senior Python Engineer", html_out)
        self.assertIn("APP998877", html_out)
        self.assertIn("Jane Doe", html_out)
        self.assertIn("accounts/profile/", html_out)

        self.assertIn("Senior Python Engineer", text_out)
        self.assertIn("APP998877", text_out)

    @override_settings(
        GMAIL_CLIENT_ID="",
        GMAIL_CLIENT_SECRET="",
        GMAIL_REFRESH_TOKEN="",
    )
    def test_emailer_gracefully_skips_when_credentials_unset(self):
        """Ensure emailer does not crash and returns False/None when credentials are not configured."""
        creds = get_gmail_credentials()
        self.assertIsNone(creds)

        result = send_gmail_message("test@example.com", "Subject", "<p>Body</p>")
        self.assertFalse(result["success"])
        self.assertIn("credentials not configured", result["error"])

    @override_settings(
        GMAIL_CLIENT_ID="mock_id",
        GMAIL_CLIENT_SECRET="mock_secret",
        GMAIL_REFRESH_TOKEN="mock_refresh",
        GMAIL_SENDER_EMAIL="DBRecruitAI <noreply@dbrecruitai.com>",
    )
    @patch("main.emailer.get_gmail_credentials")
    @patch("requests.post")
    def test_send_gmail_message_success(self, mock_post, mock_get_creds):
        """Verify message encoding and successful POST to Gmail API."""
        mock_cred_obj = MagicMock()
        mock_cred_obj.token = "mock_access_token_123"
        mock_get_creds.return_value = mock_cred_obj

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "gmail_msg_12345"}
        mock_post.return_value = mock_resp

        result = send_gmail_message(
            to_email="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test HTML</p>",
            text_content="Test Plain",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["message_id"], "gmail_msg_12345")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        self.assertIn("Authorization", call_kwargs["headers"])
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer mock_access_token_123")
        self.assertIn("raw", call_kwargs["json"])

    @override_settings(
        GMAIL_CLIENT_ID="mock_id",
        GMAIL_CLIENT_SECRET="mock_secret",
        GMAIL_REFRESH_TOKEN="mock_refresh",
    )
    @patch("main.emailer.send_gmail_message")
    def test_send_application_submitted_email_sync(self, mock_send_gmail):
        """Verify send_application_submitted_email properly populates and triggers send."""
        mock_send_gmail.return_value = {"success": True, "message_id": "msg_999"}

        ok = send_application_submitted_email(self.application, async_send=False)
        self.assertTrue(ok)
        mock_send_gmail.assert_called_once()
        _, kwargs = mock_send_gmail.call_args
        self.assertEqual(kwargs["to_email"], "candidate@example.com")
        self.assertIn("Application Received: Senior Python Engineer", kwargs["subject"])
        self.assertIn("APP998877", kwargs["html_content"])
