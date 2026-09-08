import unittest
from unittest.mock import MagicMock
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.cache import cache
from jobs.models import Job, Requirement, Application
from accounts.models import ApplicantProfile
# pyrefly: ignore [missing-import]
from jobs.recommendations import (
    normalize_text,
    _match_phrase_in_text,
    get_resume_skills,
    get_applicant_resume_data,
    analyze_applicant_resume,
    calculate_job_match,
    rank_jobs,
    get_recommended_jobs,
)


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






class RecommendationLogicTests(unittest.TestCase):
    """
    Unit tests for text normalization, resume analysis, and rubric calculation.
    """

    def test_normalize_text(self):
        self.assertEqual(normalize_text("  Python & Django!  "), "python django")
        self.assertEqual(normalize_text("C++ / C# Developer"), "c++ c# developer")
        self.assertEqual(normalize_text(None), "")

    def test_phrase_boundary_matching(self):
        # Prevent false positive: 'c' inside 'docker'
        self.assertFalse(_match_phrase_in_text("c", "experienced with docker containerization"))
        # True match
        self.assertTrue(_match_phrase_in_text("docker", "experienced with docker containerization"))
        self.assertTrue(_match_phrase_in_text("python", "knowledge of python programming"))

    def test_analyze_applicant_resume(self):
        resume_data = {
            "skills": ["Python", "Django", "PostgreSQL", "REST API"],
            "experience": [
                {
                    "job_title": "Backend Developer",
                    "company": "Tech Corp",
                    "start_date": "2020",
                    "end_date": "2023",
                    "description": "Built scalable Django microservices and REST APIs.",
                }
            ],
            "education": [
                {
                    "degree": "Bachelor of Science in Computer Science",
                    "school": "University of the Philippines",
                }
            ],
            "certifications": ["AWS Certified Cloud Practitioner"],
            "summary": "Experienced Python backend engineer.",
        }

        analyzed = analyze_applicant_resume(resume_data)

        self.assertIn("python", analyzed["skills"])
        self.assertIn("django", analyzed["skills"])
        self.assertEqual(analyzed["highest_education_level"], 3)  # Bachelor's
        self.assertGreaterEqual(analyzed["total_experience_years"], 2.0)
        self.assertIn("aws certified cloud practitioner", analyzed["certifications"])

    def test_knockout_layer_for_mandatory_license(self):
        """
        Verify that ai.py's safety knockout layer activates when a candidate
        lacks a mandatory professional license (e.g. PRC, Licensed Engineer).
        """
        job = MagicMock()
        job.title = "Civil Engineer"
        job.department = "Engineering"
        job.description = "Oversee construction and civil engineering projects."
        job.requirements = "Must have valid PRC license as Registered Civil Engineer."
        job.requirements_list.all.return_value = [
            MagicMock(text="Valid PRC Licensed Civil Engineer")
        ]

        # Applicant has skills but NO PRC license
        profile = MagicMock()
        profile.resume_data = {
            "skills": ["AutoCAD", "Site Inspection", "Estimation"],
            "experience": [
                {
                    "job_title": "Engineering Assistant",
                    "company": "Build Corp",
                    "description": "Assisted senior engineers.",
                }
            ],
            "education": [
                {"degree": "BS Civil Engineering", "school": "Mapua"}
            ],
            "certifications": [],  # No PRC license
        }
        profile.resume_text = "BS Civil Engineering graduate with AutoCAD skills."

        match = calculate_job_match(profile, job)

        self.assertTrue(match.get("hard_fail", False))
        self.assertLess(match["score"], 60)
        self.assertEqual(match["recommendation"], "Not Qualified")

    def test_exceptional_match_evaluation(self):
        job = MagicMock()
        job.title = "Senior Python Developer"
        job.department = "Engineering"
        job.description = "Looking for a Senior Python Developer with 3+ years experience in Python, Django, REST API, PostgreSQL, and Docker."
        job.requirements = "Bachelor's degree in Computer Science or related. Strong knowledge of Django, REST API, PostgreSQL."
        job.requirements_list.all.return_value = [
            MagicMock(text="Proficiency in Python, Django, and PostgreSQL"),
            MagicMock(text="Experience with Docker and REST APIs"),
        ]

        profile = MagicMock()
        profile.resume_data = {
            "skills": ["Python", "Django", "REST API", "PostgreSQL", "Docker", "Git", "Redis"],
            "experience": [
                {
                    "job_title": "Senior Python Developer",
                    "company": "Acme Inc",
                    "start_date": "2018",
                    "end_date": "2024",
                    "description": "Led backend team building Django REST APIs and Docker microservices.",
                }
            ],
            "education": [
                {"degree": "Master of Science in Computer Science", "school": "UP Diliman"}
            ],
            "certifications": ["AWS Certified Solutions Architect"],
        }
        profile.resume_text = "Master of Science in Computer Science. 6 years Python Django REST API PostgreSQL Docker experience."

        match = calculate_job_match(profile, job)

        self.assertFalse(match["hard_fail"])
        self.assertGreaterEqual(match["score"], 85)
        self.assertIn(match["match_level"], ["Exceptional", "Proficient"])
        self.assertEqual(match["recommendation"], "Qualified")
        self.assertGreaterEqual(len(match["matched_skills"]), 4)
        self.assertEqual(sum(match["criteria_weights"].values()), 100)

    def test_developing_match_evaluation(self):
        job = MagicMock()
        job.title = "Senior Financial Auditor"
        job.department = "Finance"
        job.description = "Conduct financial audit, accounting ledger reviews, and tax filings."
        job.requirements = "Degree in Accountancy. Knowledge of SAP, Tax Compliance, Financial Reporting."
        job.requirements_list.all.return_value = [
            MagicMock(text="Accounting and Financial Reporting expertise")
        ]

        # Profile has only partial / generic skills, not accounting
        profile = MagicMock()
        profile.resume_data = {
            "skills": ["Microsoft Excel", "Data Entry", "Customer Service"],
            "experience": [
                {
                    "job_title": "Administrative Clerk",
                    "company": "Retail Store",
                    "start_date": "2022",
                    "end_date": "2023",
                    "description": "Entered inventory data into spreadsheets.",
                }
            ],
            "education": [
                {"degree": "Associate in Business", "school": "City College"}
            ],
            "certifications": [],
        }
        profile.resume_text = "Administrative Clerk with Microsoft Excel skills."

        match = calculate_job_match(profile, job)

        self.assertLess(match["score"], 70)
        self.assertIn(match["match_level"], ["Developing", "Unsatisfactory"])
        self.assertEqual(match["recommendation"], "Not Qualified")

    def test_rank_jobs_ordering(self):
        job1 = MagicMock(id=1, posted_date="2026-09-01")
        job2 = MagicMock(id=2, posted_date="2026-09-02")
        job3 = MagicMock(id=3, posted_date="2026-09-03")

        recommendations = [
            {"job": job1, "score": 65, "skills_match": 60, "experience_match": 70},
            {"job": job2, "score": 92, "skills_match": 90, "experience_match": 95},
            {"job": job3, "score": 78, "skills_match": 80, "experience_match": 75},
        ]

        ranked = rank_jobs(recommendations)

        self.assertEqual(ranked[0]["job"], job2)
        self.assertEqual(ranked[0]["score"], 92)
        self.assertEqual(ranked[1]["job"], job3)
        self.assertEqual(ranked[1]["score"], 78)
        self.assertEqual(ranked[2]["job"], job1)
        self.assertEqual(ranked[2]["score"], 65)

    def test_empty_profile_handling(self):
        self.assertEqual(get_recommended_jobs(None), [])

        empty_profile = MagicMock()
        empty_profile.id = None
        empty_profile.resume_data = {}
        empty_profile.resume_text = ""
        empty_profile.default_resume = None
        self.assertEqual(get_recommended_jobs(empty_profile), [])
