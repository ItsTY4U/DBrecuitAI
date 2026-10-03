from django.shortcuts import render
from django.views.decorators.cache import cache_control

# Cache landing page at the edge for 10 minutes, serve stale up to 1 hour while revalidating
@cache_control(public=True, max_age=60, s_maxage=600, stale_while_revalidate=3600)
def index(request):
    return render(request, "main/index.html")

