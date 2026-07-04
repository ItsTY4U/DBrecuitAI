# Create your models here.
from django.db import models
from uuid import uuid4

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
    
class Application(models.Model):
    STATUS_CHOICES =[
        ("Draft", "Draft"),
        ("Pending", "Pending"),
        ("Reviewing","Reviewing"),
        ("Shortlisted","Shortlisted"),
        ("Interview","Interview"),
        ("Rejected", "Rejected"),
        ("Hired","Hired"),
    ]
    
    application_id = models.CharField(
        max_length=12,
        unique=True,
        editable=False
    )
    
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="application"
    )
    
    first_name = models.CharField(max_length=100)
    middle_initial = models.CharField(max_length=10, blank=True)
    last_name = models.CharField(max_length=100)
    
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    
    resume = models.FileField(
        upload_to = "resume/"
    )
    
    resume_processed = models.BooleanField(default=False)
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Draft"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if not self.application_id:
            self.application_id = uuid4().hex[:8].upper()
            
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.application_id} - {self.first_name} {self.last_name}"
    
    
    
    