from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.hr_login, name="hr_login"),
    path("", views.dashboard, name="dashboard"),
    
    path("jobs/", views.job_management, name="job_management"),
    path("jobs/create/", views.create_job, name="create_job"),
    path("jobs/<int:pk>/", views.manage_job, name="manage_job"),
    
    path("candidates/", views.candidates, name="candidates"),
    path("candidates/<str:department>/",views.candidate_department, name="candidate_department",),
    path("candidates/applicant/<int:pk>/", views.candidate_detail, name="candidate_detail",),
    path("applicant/<int:pk>/status/", views.update_application_status, name="update_application_status",),
    
    path("interviews/", views.interviews, name="interviews",),
    path("interviews/schedule/<int:job_id>/", views.schedule_interview, name="schedule_interview"),
    path("interviews/<int:pk>/", views.interview_detail, name="interview_detail"),
    path("interviews/<int:pk>/status/", views.update_interview_status, name="update_interview_status"),
]