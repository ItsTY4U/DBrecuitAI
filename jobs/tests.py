import json
from unittest.mock import patch, MagicMock
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

    def test_single_word_boundary_no_substring_false_positives(self):
        """Single-word skills must not match inside unrelated words (go in good, r in director, art in party)."""
        from jobs.recommendations import find_matched_skills

        applicant_skills = ["go", "r", "art"]
        job_text = "Seeking a good director for our upcoming company party."
        matched = find_matched_skills(applicant_skills, job_text)
        self.assertEqual(matched, [])

    def test_multi_word_skills_whitespace_variation(self):
        """Multi-word skills match across natural whitespace variation (spaces, tabs, newlines)."""
        from jobs.recommendations import find_matched_skills

        applicant_skills = ["public speaking", "customer service", "forklift operation"]
        job_text = "Looking for someone with public   speaking abilities, customer\nservice experience, and forklift  \t operation certification."
        matched = find_matched_skills(applicant_skills, job_text)
        self.assertEqual(matched, ["public speaking", "customer service", "forklift operation"])

    def test_special_characters_literal_matching(self):
        """Skills with regex characters (C++, C#, .NET, Node.js, R&D, e-commerce, 24/7) match literally."""
        from jobs.recommendations import find_matched_skills

        applicant_skills = ["C++", "C#", ".NET", "Node.js", "R&D", "e-commerce", "24/7", "CPR certified"]
        job_text = "We build an e-commerce platform using C#, .NET Core, and Node.js. Also seeking C++ and R&D engineers for 24/7 operations. CPR certified a plus."
        matched = find_matched_skills(applicant_skills, job_text)
        self.assertEqual(
            matched,
            ["C++", "C#", ".NET", "Node.js", "R&D", "e-commerce", "24/7", "CPR certified"]
        )

    def test_case_insensitivity_and_original_casing_preservation(self):
        """Matching is case-insensitive, but returns skills preserving the applicant's original casing and order."""
        from jobs.recommendations import find_matched_skills

        applicant_skills = ["Python", "Public Speaking", "C#", "Conflict Resolution", "Node.js"]
        job_text = "Requires python, node.js, and CONFLICT RESOLUTION skills."
        matched = find_matched_skills(applicant_skills, job_text)
        # Only Python, Conflict Resolution, Node.js matched; order and casing preserved from applicant_skills
        self.assertEqual(matched, ["Python", "Conflict Resolution", "Node.js"])

    def test_no_false_positives_for_prefix_symbols(self):
        """Skill 'C' must not match 'C++' or 'C#', and 'R' must not match 'R&D'."""
        from jobs.recommendations import find_matched_skills

        applicant_skills = ["C", "R"]
        job_text = "We are seeking C++ and C# developers, as well as an R&D technician."
        matched = find_matched_skills(applicant_skills, job_text)
        self.assertEqual(matched, [])

    def test_skips_empty_and_whitespace_skills(self):
        """Empty, whitespace-only, or non-string skills are skipped."""
        from jobs.recommendations import find_matched_skills

        applicant_skills = ["", "   ", None, "Python", "  "]
        job_text = "Looking for a Python developer."
        matched = find_matched_skills(applicant_skills, job_text)
        self.assertEqual(matched, ["Python"])


class JobsAIEngineTests(TestCase):
    def setUp(self):
        self.job = Job.objects.create(
            title="Software Engineer",
            department="Engineering",
            job_type="FULL-TIME",
            description="Build scalable Django systems.",
            status="Active"
        )
        Requirement.objects.create(job=self.job, text="Python and Django expertise")
        Requirement.objects.create(job=self.job, text="PostgreSQL experience")

    def test_parse_resume_short_circuit_empty(self):
        """parse_resume returns None immediately on empty or too-short inputs without calling API."""
        from jobs.ai import parse_resume

        self.assertIsNone(parse_resume(""))
        self.assertIsNone(parse_resume("   "))
        self.assertIsNone(parse_resume("short resume"))

    def test_analyze_resume_short_circuit_empty(self):
        """analyze_resume returns fallback dictionary when resume text is empty or unreadable."""
        from jobs.ai import analyze_resume

        res = analyze_resume("", self.job)
        self.assertEqual(res["score"], 0)
        self.assertIn("unreadable", res["summary"].lower())

    @patch("jobs.ai.get_genai_client")
    def test_parse_resume_success_with_markdown_fence(self, mock_get_client):
        """parse_resume parses JSON cleanly even if wrapped in markdown codeblocks and preambles."""
        from jobs.ai import parse_resume

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = """Here is the extracted resume JSON:
```json
{
    "personal": {
        "first_name": "Maria",
        "middle_name": "Santos",
        "last_name": "Cruz",
        "email": "maria@example.com",
        "phone": "09123456789"
    },
    "summary": "Experienced software developer.",
    "skills": ["Python", "Django", "PostgreSQL"],
    "education": [],
    "experience": [],
    "certifications": [],
    "projects": []
}
```
"""
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        resume_sample = "Maria Santos Cruz, software engineer with 5 years experience in Python and Django."
        result = parse_resume(resume_sample)

        self.assertIsNotNone(result)
        self.assertEqual(result["personal"]["first_name"], "Maria")
        self.assertEqual(result["personal"]["last_name"], "Cruz")
        self.assertIn("Django", result["skills"])

    @patch("jobs.ai.get_genai_client")
    def test_analyze_resume_calibrated_scoring(self, mock_get_client):
        """analyze_resume returns calibrated score, recommendation, and list-formatted strengths/weaknesses."""
        from jobs.ai import analyze_resume

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "score": 88,
            "recommendation": "Highly Recommended",
            "summary": "Strong match for the Software Engineer role with proven Django experience.",
            "strengths": ["Extensive Django experience", "Solid database knowledge"],
            "weaknesses": ["No explicit cloud deployment details"]
        })
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        resume_sample = "Software Engineer with 4 years building Django REST APIs and PostgreSQL backends."
        result = analyze_resume(resume_sample, self.job)

        self.assertEqual(result["score"], 88)
        self.assertEqual(result["recommendation"], "Highly Recommended")
        self.assertEqual(len(result["strengths"]), 2)
        self.assertIn("Extensive Django experience", result["strengths"])


