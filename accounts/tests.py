from django.test import TestCase, Client, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from django.contrib.auth.models import User
from accounts.models import ApplicantProfile
from accounts.forms import ApplicantProfileForm


@override_settings(
    SECURE_SSL_REDIRECT=False,
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
        """process_signup_resume throttles after 3 requests per hour."""
        from django.urls import reverse
        dummy_file = SimpleUploadedFile("resume.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")
        for _ in range(3):
            self.client.post(reverse("process_signup_resume"), {"resume": dummy_file})
        
        # 4th request should hit 429 rate limit
        response = self.client.post(reverse("process_signup_resume"), {"resume": dummy_file})
        self.assertEqual(response.status_code, 429)
        self.assertTrue(
            "Rate limit exceeded" in response.json()["error"] or "too fast" in response.json()["error"]
        )

    def test_profile_resume_update_preserves_application_resume(self):
        """When an applicant updates their profile resume, existing application resumes must not be deleted."""
        from jobs.models import Job, Application
        from django.core.files.storage import default_storage

        job = Job.objects.create(
            title="Software Engineer",
            department="Engineering",
            job_type="FULL-TIME",
            status="Active",
        )

        # 1. Profile with first resume
        first_file = SimpleUploadedFile("first_resume.pdf", b"%PDF-1.4 first version", content_type="application/pdf")
        self.profile.default_resume.save("first_resume.pdf", first_file)
        self.profile.save()
        first_path = self.profile.default_resume.name
        self.assertTrue(default_storage.exists(first_path))

        # 2. Candidate applies to job (Application references or clones the resume)
        app = Application.objects.create(
            applicant=self.user,
            job=job,
            first_name="Test",
            last_name="User",
            email=self.user.email,
            phone=self.profile.phone,
            resume=self.profile.default_resume,
            status="Pending",
        )
        self.assertEqual(app.resume.name, first_path)

        # 3. Candidate updates profile with a new resume
        second_file = SimpleUploadedFile("second_resume.pdf", b"%PDF-1.4 second version", content_type="application/pdf")
        self.profile.default_resume.save("second_resume.pdf", second_file)
        self.profile.save()

        # 4. Ensure the first resume STILL exists because the application references it!
        self.assertTrue(
            default_storage.exists(first_path),
            "First resume file was deleted even though an active application referenced it!"
        )
        self.assertTrue(default_storage.exists(self.profile.default_resume.name))

        # Clean up test files
        default_storage.delete(first_path)
        default_storage.delete(self.profile.default_resume.name)

    def test_profile_resume_update_cleans_unreferenced_file(self):
        """Unreferenced old profile resumes are cleaned up when updated if no application uses them."""
        from django.core.files.storage import default_storage

        # 1. Profile with first resume (no applications submitted)
        first_file = SimpleUploadedFile("orphan_resume.pdf", b"%PDF-1.4 orphan version", content_type="application/pdf")
        self.profile.default_resume.save("orphan_resume.pdf", first_file)
        self.profile.save()
        first_path = self.profile.default_resume.name
        self.assertTrue(default_storage.exists(first_path))

        # 2. Candidate updates profile with new resume
        second_file = SimpleUploadedFile("new_profile_resume.pdf", b"%PDF-1.4 new version", content_type="application/pdf")
        self.profile.default_resume.save("new_profile_resume.pdf", second_file)
        self.profile.save()

        # 3. First resume SHOULD be cleaned up since no application references it
        self.assertFalse(
            default_storage.exists(first_path),
            "Unreferenced old resume was not cleaned up."
        )
        self.assertTrue(default_storage.exists(self.profile.default_resume.name))

        # Clean up
        default_storage.delete(self.profile.default_resume.name)

    def test_applicant_user_form_email_readonly(self):
        """ApplicantUserForm has email marked readonly and ignores email changes."""
        from accounts.forms import ApplicantUserForm
        form = ApplicantUserForm(
            data={"first_name": "NewFirst", "last_name": "NewLast", "email": "changed@example.com"},
            instance=self.user,
        )
        self.assertEqual(form.fields["email"].widget.attrs.get("readonly"), "readonly")
        self.assertTrue(form.is_valid())
        # clean_email must preserve the original email
        self.assertEqual(form.cleaned_data["email"], self.user.email)

    def test_profile_update_allows_editing_name_and_info_but_keeps_email(self):
        """Applicants can edit their first_name, last_name, phone, address, but cannot alter sign-in email."""
        from django.urls import reverse
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("profile"),
            {
                "first_name": "UpdatedFirst",
                "last_name": "UpdatedLast",
                "email": "hacked@example.com",
                "phone": "09991234567",
                "address": "456 Updated St",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        # Refresh from database
        self.user.refresh_from_db()
        self.profile.refresh_from_db()

        # Name and profile details must be updated
        self.assertEqual(self.user.first_name, "UpdatedFirst")
        self.assertEqual(self.user.last_name, "UpdatedLast")
        self.assertEqual(self.profile.phone, "09991234567")
        self.assertEqual(self.profile.address, "456 Updated St")

        # Email must remain the original sign-in email
        self.assertEqual(self.user.email, "testuser@example.com")
        self.assertEqual(self.user.username, "testuser@example.com")

    def test_google_verify_token_flow(self):
        """Google verification token enables 1-click approval login and prevents replay."""
        from accounts.adapters import create_google_verification_token
        from django.urls import reverse

        token = create_google_verification_token(self.user, self.user.email)
        verify_url = reverse("google_verify_approve", kwargs={"token": token})

        # 1. First approval request succeeds and logs in user
        response = self.client.get(verify_url, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("profile"))

        # Check session user
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

        # 2. Second request with same token must fail (replay protection)
        self.client.logout()
        second_response = self.client.get(verify_url, follow=True)
        self.assertContains(second_response, "already been used or has expired")

    def test_google_verify_rejects_invalid_token(self):
        """Invalid Google verification tokens are rejected."""
        from django.urls import reverse
        invalid_url = reverse("google_verify_approve", kwargs={"token": "invalid:bad:token"})
        response = self.client.get(invalid_url, follow=True)
        self.assertContains(response, "The verification link is invalid")

    def test_pre_social_login_redirects_and_sends_email(self):
        """pre_social_login halts immediate login, sends verification email, and redirects to verify_sent."""
        from unittest.mock import patch, MagicMock
        from accounts.adapters import CustomSocialAccountAdapter
        from allauth.core.exceptions import ImmediateHttpResponse
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware

        factory = RequestFactory()
        request = factory.get("/accounts/google/login/callback/")
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session.save()

        adapter = CustomSocialAccountAdapter()
        sociallogin = MagicMock()
        sociallogin.is_existing = True
        sociallogin.user = self.user
        sociallogin.account.extra_data = {"email": self.user.email}

        with patch("accounts.adapters.send_gmail_message") as mock_send:
            mock_send.return_value = {"success": True, "message_id": "msg_123"}
            with self.assertRaises(ImmediateHttpResponse) as cm:
                adapter.pre_social_login(request, sociallogin)

            # Check that it redirected to google_verify_sent
            self.assertEqual(cm.exception.response.status_code, 302)
            self.assertIn("google/verify-sent/", cm.exception.response.url)
            self.assertTrue(mock_send.called)
            self.assertEqual(mock_send.call_args[1]["to_email"], self.user.email)

