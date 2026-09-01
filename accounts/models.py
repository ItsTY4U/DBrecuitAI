from django.db import models
from django.contrib.auth.models import User


class ApplicantProfile(models.Model):

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile"
    )

    middle_name = models.CharField(
        max_length=100,
        blank=True
    )

    phone = models.CharField(
        max_length=20,
        blank=True
    )

    address = models.TextField(
        blank=True
    )

    # Applicant's reusable default resume
    default_resume = models.FileField(
        upload_to="resumes/",
        blank=True,
        null=True
    )

    # Extracted text from the default resume
    resume_text = models.TextField(
        blank=True
    )

    # Structured information extracted by AI
    resume_data = models.JSONField(
        default=dict,
        blank=True
    )

    # Whether the current resume has been successfully processed
    resume_processed = models.BooleanField(
        default=False
    )

    resume_processed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.user.get_full_name() or self.user.username