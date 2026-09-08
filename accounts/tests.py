from django.test import TestCase, Client, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.contrib.auth.models import User
from accounts.models import ApplicantProfile
from accounts.forms import ApplicantProfileForm


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class AccountSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="testuser@example.com",
            email="testuser@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
        )
        self.profile = ApplicantProfile.objects.create(
            user=self.user,
            phone="09123456789",
            address="123 Street",
        )
        self.client = Client()

    def test_profile_form_rejects_non_pdf(self):
        """ApplicantProfileForm must reject non-PDF uploads."""
        bad_file = SimpleUploadedFile("malicious.exe", b"binary content", content_type="application/octet-stream")
        form = ApplicantProfileForm(
            data={"phone": "09123456789", "address": "123 Street"},
            files={"default_resume": bad_file},
            instance=self.profile
        )
        self.assertFalse(form.is_valid())
        self.assertIn("default_resume", form.errors)
        self.assertIn("Only PDF files are allowed.", form.errors["default_resume"][0])

    def test_profile_form_rejects_oversized_file(self):
        """ApplicantProfileForm must reject files exceeding 5MB."""
        large_content = b"%PDF-1.4 " + (b"0" * (6 * 1024 * 1024))
        large_file = SimpleUploadedFile("large_resume.pdf", large_content, content_type="application/pdf")
        form = ApplicantProfileForm(
            data={"phone": "09123456789", "address": "123 Street"},
            files={"default_resume": large_file},
            instance=self.profile
        )
        self.assertFalse(form.is_valid())
        self.assertIn("default_resume", form.errors)
        self.assertIn("Resume file must not exceed 5MB.", form.errors["default_resume"][0])

    def test_profile_form_accepts_valid_pdf(self):
        """ApplicantProfileForm accepts valid PDF under 5MB."""
        valid_file = SimpleUploadedFile("valid_resume.pdf", b"%PDF-1.4 sample content", content_type="application/pdf")
        form = ApplicantProfileForm(
            data={"phone": "09123456789", "address": "123 Street"},
            files={"default_resume": valid_file},
            instance=self.profile
        )
        self.assertTrue(form.is_valid())

    def test_process_signup_resume_rejects_oversized(self):
        """process_signup_resume endpoint rejects files exceeding 5MB."""
        from django.urls import reverse
        large_content = b"%PDF-1.4 " + (b"0" * (6 * 1024 * 1024))
        large_file = SimpleUploadedFile("large.pdf", large_content, content_type="application/pdf")
        response = self.client.post(reverse("process_signup_resume"), {"resume": large_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Resume file must not exceed 5MB.", response.json()["error"])

    def test_process_signup_resume_rate_limiting(self):
        """process_signup_resume throttles after 5 rapid requests."""
        from django.urls import reverse
        dummy_file = SimpleUploadedFile("resume.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")
        for _ in range(5):
            self.client.post(reverse("process_signup_resume"), {"resume": dummy_file})
        
        # 6th request should hit 429 rate limit
        response = self.client.post(reverse("process_signup_resume"), {"resume": dummy_file})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many requests", response.json()["error"])
