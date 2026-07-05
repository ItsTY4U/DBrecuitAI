from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.hr_login, name="hr_login"),
    path("", views.dashboard, name="dashboard"),
    path("jobs/", views.job_management, name="job_management"),
    path("jobs/create/", views.create_job, name="create_job"),
    path("jobs/<int:pk>/", views.manage_job, name="manage_job"),
]