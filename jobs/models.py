# Create your models here.
from django.db import models


class Job(models.Model):
    JOB_TYPES = [
        ("FULL-TIME", "Full-Time"),
        ("PART-TIME", "Part-Time"),
    ]

    STATUS_CHOICES = [
        ("Open", "Open"),
        ("Closed", "Closed"),
    ]

    title = models.CharField(max_length=100)
    department = models.CharField(max_length=100)
    job_type = models.CharField(max_length=20, choices=JOB_TYPES)
    description = models.TextField(blank=True)

    requirements = models.TextField(blank=True)

    posted_date = models.DateField(auto_now_add=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Open"
    )

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title
    
class Requirement(models.Model):
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="requirements_list"
    )
    text = models.CharField(max_length=255)

    def __str__(self):
        return self.text