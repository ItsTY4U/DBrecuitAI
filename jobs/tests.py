from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.cache import cache
from jobs.models import Job, Requirement, Application
from accounts.models import ApplicantProfile
from jobs.recommendations import get_recommended_jobs


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class ApplicantJobPerformanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username="testapplicant@example.com",
            email="testapplicant@example.com",
            password="password123",
            first_name="Alex",
            last_name="Reyes"
        )
        self.profile = ApplicantProfile.objects.create(
            user=self.user,
            resume_processed=False,
            resume_data={},
            resume_text=""
        )
        self.job = Job.objects.create(
            title="Barista",
            department="Operations",
            job_type="FULL-TIME",
            description="Prepare drinks",
            status="Active"
        )
        self.req1 = Requirement.objects.create(job=self.job, text="Customer service skills")
        self.req2 = Requirement.objects.create(job=self.job, text="Coffee brewing knowledge")

    def test_jobs_view_full_page(self):
        """Standard GET request returns full page HTML with doctype."""
        response = self.client.get(reverse("jobs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<!DOCTYPE html>")
        self.assertContains(response, "Barista")

    def test_jobs_view_htmx_partial_request(self):
        """HTMX search / filter request returns only partial without full document doctype."""
        response = self.client.get(
            reverse("jobs") + "?q=Barista",
            HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<!DOCTYPE html>")
        self.assertNotContains(response, "<body")
        self.assertContains(response, "job-card")
        self.assertContains(response, "Barista")

    def test_job_detail_prefetches_requirements(self):
        """Visiting job_detail renders requirements efficiently."""
        url = reverse("job_detail", kwargs={"id": self.job.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customer service skills")
        self.assertContains(response, "Coffee brewing knowledge")

    def test_recommendations_early_exit_no_skills(self):
        """Applicants without skills trigger 0 Job queries and return immediately."""
        with self.assertNumQueries(0):
            recs = get_recommended_jobs(self.profile)
            self.assertEqual(recs, [])

    def test_recommendations_caching(self):
        """Applicants with skills have their recommendations cached."""
        self.profile.resume_data = {"skills": ["coffee brewing", "customer service"]}
        self.profile.resume_processed = True
        self.profile.save()

        # First call fetches from DB and caches
        recs1 = get_recommended_jobs(self.profile)
        self.assertEqual(len(recs1), 1)
        self.assertEqual(recs1[0]["job"].id, self.job.id)

        # Second call hits cache (0 DB queries)
        with self.assertNumQueries(0):
            recs2 = get_recommended_jobs(self.profile)
            self.assertEqual(len(recs2), 1)
            self.assertEqual(recs2[0]["score"], recs1[0]["score"])
