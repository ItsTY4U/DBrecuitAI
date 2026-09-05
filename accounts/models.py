import os
from django.db import models
from django.contrib.auth.models import User


def applicant_resume_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".pdf"
    user_id = instance.user_id or "applicant"
    return f"resumes/user_{user_id}_resume{ext}"


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

    # Applicant's reusable default resume - single object per user in R2
    default_resume = models.FileField(
        upload_to=applicant_resume_upload_path,
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

    def save(self, *args, **kwargs):
        # Clean up previous resume object in R2 when updated
        if self.pk:
            try:
                old_profile = ApplicantProfile.objects.get(pk=self.pk)
                if (
                    old_profile.default_resume
                    and old_profile.default_resume.name != self.default_resume.name
                ):
                    old_profile.default_resume.delete(save=False)
            except ApplicantProfile.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.default_resume:
            try:
                self.default_resume.delete(save=False)
            except Exception:
                pass
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.user.get_full_name() or self.user.username