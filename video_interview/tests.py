from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from jobs.models import Job, Application
from video_interview.models import BehavioralQuestion, InterviewSession, InterviewResponse
from video_interview.ai import analyze_interview_session
from unittest.mock import patch, MagicMock


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    ASYNC_VIDEO_ANALYSIS=False,
)
class VideoInterviewTests(TestCase):
    def setUp(self):
        # Create users
        self.applicant_user = User.objects.create_user(
            username="applicant@example.com",
            email="applicant@example.com",
            password="testpassword123",
            first_name="Juan",
            last_name="Dela Cruz"
        )
        self.other_user = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="testpassword123",
            first_name="Maria",
            last_name="Santos"
        )
        self.staff_user = User.objects.create_user(
            username="hradmin",
            email="hr@example.com",
            password="testpassword123",
            is_staff=True
        )

        # Create Job
        self.job = Job.objects.create(
            title="Barista",
            department="Operations",
            job_type="FULL-TIME",
            description="Barista role",
            status="Active"
        )

        # Create Application
        self.application = Application.objects.create(
            applicant=self.applicant_user,
            job=self.job,
            first_name="Juan",
            last_name="Dela Cruz",
            email="applicant@example.com",
            phone="09123456789",
            status="Pending"
        )

        # Create behavioral questions
        for i in range(5):
            BehavioralQuestion.objects.create(
                job=self.job,
                question_text=f"Behavioral question #{i+1} for {self.job.title}",
                category="Teamwork",
                is_active=True
            )

        self.client = Client()

    def test_welcome_view_authenticated_owner(self):
        self.client.login(username="applicant@example.com", password="testpassword123")
        url = reverse("video_interview:welcome", kwargs={"application_id": self.application.application_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome to Your AI Video Interview")
        self.assertContains(response, "Strict No-Retake Policy")

    def test_welcome_view_unauthorized_user(self):
        self.client.login(username="other@example.com", password="testpassword123")
        url = reverse("video_interview:welcome", kwargs={"application_id": self.application.application_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)  # Redirected to profile

    def test_start_interview_creates_5_questions(self):
        self.client.login(username="applicant@example.com", password="testpassword123")
        start_url = reverse("video_interview:start", kwargs={"application_id": self.application.application_id})
        response = self.client.post(start_url)
        self.assertEqual(response.status_code, 302)

        session = InterviewSession.objects.get(application=self.application)
        self.assertEqual(session.status, "IN_PROGRESS")
        self.assertEqual(session.responses.count(), 5)

        # 2 intro questions
        intro_count = session.responses.filter(question_type="INTRO").count()
        behavioral_count = session.responses.filter(question_type="BEHAVIORAL").count()
        self.assertEqual(intro_count, 2)
        self.assertEqual(behavioral_count, 3)

    def test_leave_interview_marks_abandoned(self):
        self.client.login(username="applicant@example.com", password="testpassword123")
        # Start
        self.client.post(reverse("video_interview:start", kwargs={"application_id": self.application.application_id}))
        # Leave
        leave_url = reverse("video_interview:leave", kwargs={"application_id": self.application.application_id})
        response = self.client.post(leave_url)
        self.assertEqual(response.status_code, 302)

        session = InterviewSession.objects.get(application=self.application)
        self.assertEqual(session.status, "ABANDONED")

        # Now attempting to visit welcome view shows already_taken screen
        welcome_url = reverse("video_interview:welcome", kwargs={"application_id": self.application.application_id})
        resp2 = self.client.get(welcome_url)
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "Interview Session Closed")

    def test_hr_can_reset_interview_for_retake(self):
        session = InterviewSession.objects.create(
            application=self.application,
            status="ABANDONED"
        )
        self.client.login(username="hradmin", password="testpassword123")
        reset_url = reverse("reset_candidate_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(reset_url)
        self.assertEqual(response.status_code, 302)

        session.refresh_from_db()
        self.assertTrue(session.can_retake)
        self.assertEqual(session.status, "PENDING")

        # Applicant can now access welcome again
        self.client.login(username="applicant@example.com", password="testpassword123")
        welcome_url = reverse("video_interview:welcome", kwargs={"application_id": self.application.application_id})
        resp2 = self.client.get(welcome_url)
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "Welcome to Your AI Video Interview")

    def test_submit_answer_api(self):
        self.client.login(username="applicant@example.com", password="testpassword123")
        self.client.post(reverse("video_interview:start", kwargs={"application_id": self.application.application_id}))

        submit_url = reverse("video_interview:submit_answer", kwargs={"application_id": self.application.application_id})
        resp = self.client.post(submit_url, {
            "question_number": 1,
            "skipped": "true",
            "duration_seconds": 15
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])

        session = InterviewSession.objects.get(application=self.application)
        q1 = session.responses.get(question_number=1)
        self.assertTrue(q1.skipped)
        self.assertEqual(q1.duration_seconds, 15)

    def test_finish_interview_computes_score_and_completes(self):
        self.client.login(username="applicant@example.com", password="testpassword123")
        self.client.post(reverse("video_interview:start", kwargs={"application_id": self.application.application_id}))

        finish_url = reverse("video_interview:finish", kwargs={"application_id": self.application.application_id})
        response = self.client.get(finish_url)
        self.assertEqual(response.status_code, 302)

        session = InterviewSession.objects.get(application=self.application)
        self.assertEqual(session.status, "COMPLETED")
        self.assertTrue(session.final_score >= 50 and session.final_score <= 100)

    @override_settings(ASYNC_VIDEO_ANALYSIS=True)
    @patch("threading.Thread.start")
    def test_finish_interview_async_redirects_immediately(self, mock_thread_start):
        self.client.login(username="applicant@example.com", password="testpassword123")
        self.client.post(reverse("video_interview:start", kwargs={"application_id": self.application.application_id}))

        finish_url = reverse("video_interview:finish", kwargs={"application_id": self.application.application_id})
        response = self.client.get(finish_url)
        self.assertEqual(response.status_code, 302)

        session = InterviewSession.objects.get(application=self.application)
        self.assertEqual(session.status, "COMPLETED")
        self.assertTrue(mock_thread_start.called)


    @patch("video_interview.ai.get_genai_client")
    def test_remote_storage_backend_not_implemented_path_handled(self, mock_get_client):
        """
        Verify that when a storage backend raises NotImplementedError for .path
        (such as S3 / Cloudflare R2), analyze_single_response downloads to a temp file
        instead of failing with 'This backend doesn't support absolute paths.'
        """
        from video_interview.ai import analyze_single_response
        import json

        # Set up mock Gemini client
        mock_client = MagicMock()
        mock_uploaded_file = MagicMock()
        mock_uploaded_file.name = "files/test_file_123"
        mock_uploaded_file.state.name = "ACTIVE"
        mock_client.files.upload.return_value = mock_uploaded_file

        mock_gemini_resp = MagicMock()
        mock_gemini_resp.text = json.dumps({
            "score": 88,
            "transcript": "I am a strong candidate with relevant experience.",
            "feedback": "Clear explanation and great examples.",
            "strengths": ["Clear delivery"],
            "improvements": ["Could be slightly more concise"]
        })
        mock_client.models.generate_content.return_value = mock_gemini_resp
        mock_get_client.return_value = mock_client

        # Mock a video response where .path raises NotImplementedError (like S3/R2)
        mock_response = MagicMock()
        mock_response.skipped = False
        mock_response.question_number = 1
        mock_response.question_text = "Tell us about yourself"
        mock_response.get_question_type_display.return_value = "Introduction"

        mock_clip = MagicMock()
        type(mock_clip).path = property(lambda self: (_ for _ in ()).throw(NotImplementedError("This backend doesn't support absolute paths.")))
        mock_clip.name = "interview_clips/test_video.webm"
        mock_clip.chunks.return_value = [b"fake-video-chunk-1", b"fake-video-chunk-2"]
        mock_response.video_clip = mock_clip

        result = analyze_single_response(mock_response, "Barista", "Operations")

        self.assertEqual(result["score"], 88)
        self.assertEqual(result["transcript"], "I am a strong candidate with relevant experience.")
        self.assertNotIn("temporary delay", result["feedback"])
        self.assertEqual(result["feedback"], "Clear explanation and great examples.")
        mock_client.files.upload.assert_called_once()
        mock_client.files.delete.assert_called_once_with(name="files/test_file_123")

    def test_hr_can_reanalyze_candidate_interview(self):
        session = InterviewSession.objects.create(
            application=self.application,
            status="COMPLETED"
        )
        InterviewResponse.objects.create(
            session=session,
            question_number=1,
            question_type="INTRO",
            question_text="Tell us about yourself",
            skipped=True
        )
        self.client.login(username="hradmin", password="testpassword123")
        reanalyze_url = reverse("reanalyze_candidate_interview", kwargs={"pk": self.application.pk})
        response = self.client.post(reanalyze_url)
        self.assertEqual(response.status_code, 302)
        session.refresh_from_db()
        self.assertTrue(session.ai_analyzed)
