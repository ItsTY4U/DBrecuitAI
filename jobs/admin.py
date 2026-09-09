from django.contrib import admin
from .models import Job, Requirement, Application

# Register your models here.
class KeyQualificationInline(admin.TabularInline):
    model = Requirement
    verbose_name = "Key Qualification"
    verbose_name_plural = "Key Qualifications (AI Screening Criteria)"
    extra = 1
    fields = ("text",)

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "job_type", "status", "posted_date")
    list_filter = ("department", "job_type", "status")
    search_fields = ("title", "department", "description", "requirements")

    fieldsets = (
        ("Basic Information", {
            "fields": ("title", "department", "job_type", "status"),
        }),
        ("Role Description", {
            "fields": ("description",),
        }),
        ("General Requirements (Applicant-Facing)", {
            "fields": ("requirements",),
            "description": "General requirements displayed to prospective candidates on the job board.",
        }),
    )

    inlines = [KeyQualificationInline]

@admin.register(Requirement)
class KeyQualificationAdmin(admin.ModelAdmin):
    list_display = ("text", "job", "get_department")
    list_filter = ("job__department", "job__status", "job")
    search_fields = ("text", "job__title", "job__department")

    @admin.display(description="Department")
    def get_department(self, obj):
        return obj.job.department

@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "application_id",
        "first_name",
        "middle_initial",
        "last_name",
        "job",
        "status",
        "created_at",
    )
    list_filter = ("status", "job")
    search_fields = (
        "application_id",
        "first_name",
        "middle_initial",
        "last_name",
        "email",
    )
