from django.contrib import admin
from django.urls import include, path

from core import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]
