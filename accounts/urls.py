from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("login/", views.applicant_login, name="applicant_login"),
    path("logout/", views.applicant_logout, name="applicant_logout"),
    path("profile/", views.profile, name="profile"),
    path(
    "process-signup-resume/",
    views.process_signup_resume,
    name="process_signup_resume"
),
]
