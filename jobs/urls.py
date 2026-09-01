from django.urls import path
from . import views

urlpatterns = [
    path('', views.jobs, name='jobs'),
    path('<int:id>/', views.job_detail, name='job_detail'),
    path('<int:pk>/apply/', views.apply_job, name='apply'),
    path('<int:pk>/upload-resume/', views.upload_resume, name='upload_resume'),
    path('application/<str:application_id>/success/', views.application_success, name='application_success'),
]