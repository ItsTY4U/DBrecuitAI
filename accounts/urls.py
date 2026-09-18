from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.applicant_login, name="applicant_login"),
    path("logout/", views.applicant_logout, name="applicant_logout"),
    path("profile/", views.profile, name="profile"),
    path(
    "process-signup-resume/",
    views.process_signup_resume,
    name="process_signup_resume"
),
    path("forgot-password/", views.forgot_password, name="forgot_password"),
    path("verify-otp/", views.verify_password_otp, name="verify_password_otp"),
    path("google/verify-sent/", views.google_verify_sent, name="google_verify_sent"),
    path("google/verify/<str:token>/", views.google_verify_approve, name="google_verify_approve"),
    path("google/resend-verify/", views.resend_google_verify, name="resend_google_verify"),
]
