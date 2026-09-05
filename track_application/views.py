from django.shortcuts import render
from jobs.models import Application

# Create your views here.
def track(request):
    return render(request, "applications/track.html")

def track_application(request):
    application_id = request.GET.get("application_id", "").strip()
    application = Application.objects.filter(
        application_id=application_id
    ).select_related("job").first()
    
    return render(request, "applications/partials/tracking_result.html", {
        "application": application
    })