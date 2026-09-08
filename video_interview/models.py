import os
from django.db import models
from jobs.models import Application, Job


class BehavioralQuestion(models.Model):
    """
    Pre-defined behavioral questions configured by HR per job or globally.
    """
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="behavioral_questions",
        null=True,
        blank=True,
        help_text="Leave blank to make this a default question across all jobs."
    )
    question_text = models.CharField(max_length=500)
    category = models.CharField(max_length=100, blank=True, default="General")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        job_label = self.job.title if self.job else "Global"
        return f"[{job_label}] {self.question_text[:60]}..."


class InterviewSession(models.Model):
    """
    Tracks the overall video interview session for a job application.
    Limited to 1 attempt per job unless granted retake for technical issues.
    """
    STATUS_CHOICES = [
        ("PENDING", "Pending (Not Started)"),
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("ABANDONED", "Abandoned"),
    ]

    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name="video_interview"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    final_score = models.IntegerField(null=True, blank=True, help_text="Score between 50 and 100")
    overall_feedback = models.TextField(blank=True)
    overall_summary = models.TextField(blank=True)
    ai_analyzed = models.BooleanField(default=False)

    can_retake = models.BooleanField(
        default=False,
        help_text="Set by HR to allow applicant to retake interview after technical issues."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Interview for {self.application.application_id} ({self.get_status_display()})"

    @property
    def is_locked(self):
        """Returns True if the interview cannot be taken/retaken."""
        if self.can_retake:
            return False
        return self.status in ["COMPLETED", "ABANDONED"]

    @property
    def can_start_or_resume(self):
        """Returns True if applicant can begin or continue."""
        if self.can_retake:
            return True
        return self.status in ["PENDING", "IN_PROGRESS"]


def interview_video_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".webm"
    app_id = instance.session.application.application_id
    return f"videos/{app_id}_q{instance.question_number}{ext}"


class InterviewResponse(models.Model):
    """
    Stores the video recording, transcription, and AI score/feedback for each of the 5 questions.
    """
    QUESTION_TYPES = [
        ("INTRO", "Introduction Question"),
        ("BEHAVIORAL", "Behavioral Question"),
    ]

    session = models.ForeignKey(
        InterviewSession,
        on_delete=models.CASCADE,
        related_name="responses"
    )
    question_number = models.IntegerField(help_text="1 to 5")
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default="BEHAVIORAL")
    question_text = models.CharField(max_length=500)

    video_clip = models.FileField(
        upload_to=interview_video_upload_path,
        null=True,
        blank=True
    )
    skipped = models.BooleanField(default=False)
    duration_seconds = models.IntegerField(default=0)

    score = models.IntegerField(null=True, blank=True, help_text="Question score 50-100")
    transcript = models.TextField(blank=True)
    feedback = models.TextField(blank=True)
    strengths = models.TextField(blank=True)
    improvements = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Clean up previous video clip in storage when replaced
        if self.pk:
            try:
                old_resp = InterviewResponse.objects.get(pk=self.pk)
                if (
                    old_resp.video_clip
                    and old_resp.video_clip.name != (self.video_clip.name if self.video_clip else None)
                ):
                    old_resp.video_clip.delete(save=False)
            except InterviewResponse.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.video_clip:
            try:
                self.video_clip.delete(save=False)
            except Exception:
                pass
        super().delete(*args, **kwargs)

    class Meta:
        ordering = ["question_number"]
        unique_together = [("session", "question_number")]

    def __str__(self):
        return f"Q{self.question_number} Response for {self.session.application.application_id}"

