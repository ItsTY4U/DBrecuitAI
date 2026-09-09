import os
import uuid
from django.db import models
from django.contrib.auth.models import User


def applicant_resume_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".pdf"
    user_id = instance.user_id or uuid.uuid4().hex[:8]
    unique_token = uuid.uuid4().hex[:6]
    return f"resumes/user_{user_id}_{unique_token}_resume{ext}"


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
        # Clean up previous resume object when updated, but ONLY if not referenced by any Application
        if self.pk:
            try:
                old_profile = ApplicantProfile.objects.get(pk=self.pk)
                if (
                    old_profile.default_resume
                    and old_profile.default_resume.name
                    and old_profile.default_resume.name != (self.default_resume.name if self.default_resume else "")
                ):
                    from django.apps import apps
                    Application = apps.get_model("jobs", "Application")
                    is_used = Application.objects.filter(
                        resume=old_profile.default_resume.name
                    ).exists()
                    if not is_used:
                        old_profile.default_resume.delete(save=False)
            except ApplicantProfile.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.default_resume and self.default_resume.name:
            try:
                from django.apps import apps
                Application = apps.get_model("jobs", "Application")
                is_used = Application.objects.filter(
                    resume=self.default_resume.name
                ).exists()
                if not is_used:
                    self.default_resume.delete(save=False)
            except Exception:
                pass
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.user.get_full_name() or self.user.username