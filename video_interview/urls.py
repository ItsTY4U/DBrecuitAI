from django.urls import path
from . import views

app_name = "video_interview"

urlpatterns = [
    path("<str:application_id>/welcome/", views.welcome_view, name="welcome"),
    path("<str:application_id>/start/", views.start_interview_view, name="start"),
    path("<str:application_id>/room/", views.interview_room_view, name="room"),
    path("<str:application_id>/question-audio/<int:question_number>/", views.question_audio_api, name="question_audio"),
    path("<str:application_id>/submit-answer/", views.submit_answer_api, name="submit_answer"),
    path("<str:application_id>/finish/", views.finish_interview_view, name="finish"),
    path("<str:application_id>/leave/", views.leave_interview_view, name="leave"),
    path("<str:application_id>/congratulations/", views.congratulations_view, name="congratulations"),
    path("stream/<int:response_id>/", views.stream_video_clip, name="stream_clip"),
]
