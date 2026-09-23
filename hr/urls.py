from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.hr_login, name="hr_login"),
    path("logout/", views.hr_logout, name="hr_logout"),
    path("", views.dashboard, name="dashboard"),
    
    path("jobs/", views.job_management, name="job_management"),
    path("jobs/create/", views.create_job, name="create_job"),
    path("jobs/<int:pk>/", views.manage_job, name="manage_job"),
    path("departments/create/", views.create_department, name="create_department"),
    
    path("candidates/", 
        views.candidates, 
        name="candidates"),

    path(
        "candidates/job/<int:job_id>/table/",
        views.candidate_job_table,
        name="candidate_job_table",
    ),

    path(
        "candidates/department/<str:department>/",
        views.candidate_department,
        name="candidate_department",
    ),

    path("candidates/applicant/<int:pk>/", 
        views.candidate_detail, 
        name="candidate_detail",
        ),

    path("candidates/applicant/<int:pk>/reset-interview/", 
        views.reset_candidate_interview, 
        name="reset_candidate_interview",
        ),

    path("candidates/applicant/<int:pk>/reanalyze-interview/", 
        views.reanalyze_candidate_interview, 
        name="reanalyze_candidate_interview",
        ),


    path("candidates/applicant/<int:pk>/send-email/", 
        views.send_candidate_email, 
        name="send_candidate_email",
        ),

    path("candidates/applicant/<int:pk>/evaluate/",
        views.evaluate_candidate,
        name="evaluate_candidate",
        ),

    path("candidates/applicant/<int:pk>/start-evaluation/",
        views.start_candidate_evaluation,
        name="start_candidate_evaluation",
        ),

    path("candidates/applicant/<int:pk>/cancel-evaluation/",
        views.cancel_candidate_evaluation,
        name="cancel_candidate_evaluation",
        ),

    path("applicant/<int:pk>/status/", 
        views.update_application_status, 
        name="update_application_status",),

    path("reports/", views.reports_dashboard, name="reports"),
    
    path("interviews/", views.interviews, name="interviews",),
    path("interviews/schedule/<int:job_id>/", views.schedule_interview, name="schedule_interview"),
    path("interviews/<int:pk>/", views.interview_detail, name="interview_detail"),
    path("interviews/<int:pk>/status/", views.update_interview_status, name="update_interview_status"),
]