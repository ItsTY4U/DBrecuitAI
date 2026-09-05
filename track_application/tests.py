from django.test import TestCase, Client, override_settings
from django.urls import reverse
from jobs.models import Job, Application


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class TrackApplicationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.job = Job.objects.create(
            title="Accountant",
            department="Finance",
            job_type="FULL-TIME",
            status="Active"
        )
        self.app_active = Application.objects.create(
            job=self.job,
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
            phone="09111222333",
            status="Screening"
        )
        self.app_hired = Application.objects.create(
            job=self.job,
            first_name="Bob",
            last_name="Smith",
            email="bob@example.com",
            phone="09444555666",
            status="Hired"
        )

    def test_track_application_renders_with_select_related(self):
        """View renders application and job title."""
        response = self.client.get(
            reverse("track_application"),
            {"application_id": self.app_active.application_id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accountant")
        self.assertContains(response, "Screening")

    def test_track_page_loads_supabase_sdk(self):
        """Track page contains the Supabase JS client CDN."""
        response = self.client.get(reverse("track"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2")

    def test_active_application_subscribes_to_realtime(self):
        """Active applications subscribe to Supabase Realtime channel and do not poll."""
        response = self.client.get(
            reverse("track_application"),
            {"application_id": self.app_active.application_id}
        )
        self.assertContains(response, "application-status-")
        self.assertContains(response, "postgres_changes")
        self.assertNotContains(response, 'hx-trigger="every 10s"')

    def test_terminal_application_stops_realtime(self):
        """Completed applications do not subscribe to Realtime updates and do not poll."""
        response = self.client.get(
            reverse("track_application"),
            {"application_id": self.app_hired.application_id}
        )
        self.assertNotContains(response, "application-status-")
        self.assertNotContains(response, 'hx-trigger="every 10s"')
