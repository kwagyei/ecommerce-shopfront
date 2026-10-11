from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    return render(request, "home.html")


def healthz(request):
    """Liveness probe: cheap, no database access, used by the host to check the app is up."""
    return JsonResponse({"status": "ok"})
