import unittest
from unittest.mock import MagicMock
from django.test import TestCase
# pyrefly: ignore [missing-import]
from django.contrib.auth.models import User
from accounts.models import ApplicantProfile
from jobs.models import Job, Requirement
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
