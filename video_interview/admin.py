from django.contrib import admin
from .models import BehavioralQuestion, InterviewSession, InterviewResponse


class InterviewResponseInline(admin.TabularInline):
    model = InterviewResponse
    extra = 0
    fields = ("question_number", "question_type", "question_text", "score", "skipped", "duration_seconds")
    readonly_fields = ("question_number", "question_type", "question_text")


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = ("application", "status", "final_score", "ai_analyzed", "can_retake", "started_at", "completed_at")
    list_filter = ("status", "ai_analyzed", "can_retake")
    search_fields = ("application__application_id", "application__first_name", "application__last_name", "application__email")
    inlines = [InterviewResponseInline]
    actions = ["allow_retake", "reset_interview"]

    @admin.action(description="Allow applicant to retake interview (for technical issues)")
    def allow_retake(self, request, queryset):
        for session in queryset:
            for resp in session.responses.all():
                if resp.video_clip:
                    try:
                        resp.video_clip.delete(save=False)
                    except Exception:
                        pass
            session.responses.all().delete()
            session.can_retake = True
            session.status = "PENDING"
            session.final_score = None
            session.overall_feedback = ""
            session.overall_summary = ""
            session.ai_analyzed = False
            session.started_at = None
            session.completed_at = None
            session.save()
        self.message_user(request, "Selected interviews have been unlocked for retake and old video files cleared.")

    @admin.action(description="Reset interview session")
    def reset_interview(self, request, queryset):
        for session in queryset:
            for resp in session.responses.all():
                if resp.video_clip:
                    try:
                        resp.video_clip.delete(save=False)
                    except Exception:
                        pass
            session.responses.all().delete()
            session.status = "PENDING"
            session.can_retake = False
            session.final_score = None
            session.overall_feedback = ""
            session.overall_summary = ""
            session.ai_analyzed = False
            session.started_at = None
            session.completed_at = None
            session.save()
        self.message_user(request, "Selected interviews have been reset and old video files cleared.")


@admin.register(BehavioralQuestion)
class BehavioralQuestionAdmin(admin.ModelAdmin):
    list_display = ("question_text", "job", "category", "is_active", "created_at")
    list_filter = ("category", "is_active", "job")
    search_fields = ("question_text", "category")


@admin.register(InterviewResponse)
class InterviewResponseAdmin(admin.ModelAdmin):
    list_display = ("session", "question_number", "question_type", "score", "skipped")
    list_filter = ("question_type", "skipped")
