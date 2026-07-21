from django.contrib import admin
from .models import Interview
# Register your models here.
@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = (
        "interview_type",
        "date",
        "time",
        "status",
    )
    
    filter_horizontal = (
        "applicants",
    )