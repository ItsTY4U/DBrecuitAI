from django.contrib import admin
from .models import Job, Requirement, Application

# Register your models here.
class RequirementInline(admin.TabularInline):
    model = Requirement
    extra = 1
    
@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "job_type", "status")
    list_filter = ("department", "job_type", "status")
    search_fields = ("title", "department")
    
    inlines = [RequirementInline]
    
admin.site.register(Requirement)

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
