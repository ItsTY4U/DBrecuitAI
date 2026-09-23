from django.db import models
from jobs.models import Application
from django.contrib.auth.models import User
from django.utils import timezone
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


class CandidateEvaluation(models.Model):
    INTERVIEW_MODE_CHOICES = [
        ("Face-to-Face", "Face-to-Face"),
        ("Online", "Online (Google Meet / Zoom)"),
        ("Phone Call", "Phone Call"),
    ]

    RECOMMENDATION_CHOICES = [
        ("Strong Hire", "Strong Hire"),
        ("Hire", "Hire"),
        ("Hold", "Hold / Further Review"),
        ("No Hire", "Do Not Hire"),
    ]

    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("Completed", "Completed"),
    ]

    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name="evaluation"
    )
    interview = models.ForeignKey(
        Interview,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations"
    )
    evaluator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations_conducted"
    )
    evaluator_name = models.CharField(max_length=150, blank=True)
    interview_mode = models.CharField(
        max_length=30,
        choices=INTERVIEW_MODE_CHOICES,
        default="Face-to-Face"
    )
    evaluation_date = models.DateField(default=timezone.now)

    # Competency Rubric Ratings (1-5)
    technical_competence = models.IntegerField(default=3)
    communication_skills = models.IntegerField(default=3)
    problem_solving = models.IntegerField(default=3)
    cultural_fit = models.IntegerField(default=3)
    leadership_potential = models.IntegerField(default=3)
    overall_rating = models.DecimalField(max_digits=4, decimal_places=1, default=3.0)

    # Structured Qualitative Notes
    strengths_notes = models.TextField(blank=True)
    weaknesses_notes = models.TextField(blank=True)
    general_notes = models.TextField(blank=True)

    # Audio Recording & AI Audio Intelligence
    audio_file = models.FileField(
        upload_to="interview_audio/%Y/%m/",
        blank=True,
        null=True
    )
    ai_audio_transcript = models.TextField(blank=True)
    ai_audio_summary = models.TextField(blank=True)
    ai_audio_score = models.IntegerField(default=0)
    ai_audio_insights = models.JSONField(default=dict, blank=True)

    # Practical HR Details
    expected_salary = models.CharField(max_length=100, blank=True)
    notice_period = models.CharField(max_length=100, blank=True)
    availability_date = models.CharField(max_length=100, blank=True)

    # Decision & Status
    recommendation = models.CharField(
        max_length=30,
        choices=RECOMMENDATION_CHOICES,
        default="Hire"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Completed"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-evaluation_date", "-created_at"]

    def __str__(self):
        return f"Evaluation: {self.application.first_name} {self.application.last_name} ({self.overall_rating}/5)"

    def calculate_overall(self):
        scores = [
            self.technical_competence or 3,
            self.communication_skills or 3,
            self.problem_solving or 3,
            self.cultural_fit or 3,
            self.leadership_potential or 3,
        ]
        return round(sum(scores) / len(scores), 1)

    def save(self, *args, **kwargs):
        self.overall_rating = self.calculate_overall()
        super().save(*args, **kwargs)