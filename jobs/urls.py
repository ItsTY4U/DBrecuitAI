from django.urls import path

from . import views

urlpatterns = [
    path("", views.jobs, name="jobs"),
    path("<int:id>/", views.job_detail, name="job_detail"),
    path("<int:pk>/apply/", views.apply_job, name="apply"),
    path("<int:pk>/upload/>", views.upload_resume, name="upload_resume"),
]