from django.shortcuts import render
from .models import Application

# Create your views here.
def track(request):
    return render(render, "applications/track.html")

def track_application(request):
    application_id = reques.GET.get("application_id")
    application = Application.object.filter(
        application_id=application_id
    ).first()
    
    return render(request, "applications/partials/tracking_result.html", {
        "application": application
    })