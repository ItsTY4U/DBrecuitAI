from django.db import models
from jobs.models import Application
from django.contrib.auth.models import User
# Create your models here.
class Interview(models.Model):
    STATUS_CHOICES = [
        ("Scheduled", "Scheduled"),
        ("Ongoing","Ongoing"),
        ("Completed", "Completed"),
        ("Cancelled", "Cancelled"),
    ]
    
    TYPE_CHOICES = [
        ("HR Interview", "HR Interview"),
        ("Technical Interview", "Technical Interview"),
        ("Final Interview", "Final Interview")
    ]
    
    interview_type = models.CharField(
        max_length=30,
        choices=TYPE_CHOICES
    )
    
    interviewer = models.CharField(max_length=100)
    
    

    # interviewer = models.ForeignKey(
    #     User,
    #     on_delete=models.SET_NULL,
    #     null=True,
    #     blank=True
    # )
    
    date = models.DateField()
    time = models.TimeField()
    location = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Scheduled"
    )
    applicants = models.ManyToManyField(
        Application,
        related_name="interview"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ["date", "time"]
    
    def __str__(self):
        return f"{self.interview_type} - {self.date}"

    @property
    def primary_applicant(self):
        """Returns first applicant using prefetched in-memory cache if available."""
        apps = self.applicants.all()
        return apps[0] if apps else None

    @property
    def primary_job(self):
        """Returns the job associated with the primary applicant without extra queries."""
        applicant = self.primary_applicant
        return applicant.job if applicant else None

    