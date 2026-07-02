from django.db import models
from jobs.models import Job
import uuid
# Create your models here.
class Application(models.Model):
    STATUS_CHOICES = [
        ("Received", "Received"),
        ("Screening", "Screening"),
        ("Interview", "Interview"),
        ("Hired", "Hired"),
        ("Rejected", "Rejected"),
    ]

    job = models.ForeignKey(Job, on_delete=models.CASCADE)

    application_id = models.CharField(
        max_length=20,
        unique=True,
        editable=False
    )

    full_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)

    resume = models.FileField(upload_to="resumes/")

    applied_date = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Received"
    )

    def save(self, *args, **kwargs):
        if not self.application_id:
            self.application_id = str(uuid.uuid4())[:8].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name