from django.urls import path

from . import views

urlpatterns = [
    path("", views.track, name="track"),
    path("search/", views.track_application, name="track_application")
]


