"""Canon §8.1 — API pod /api/v1/. Van toga `/healthz`, početna strana i
kontrolna tabla `/console/` (ADR-0010)."""

from django.urls import include, path

from api.views.ops import healthz, home

urlpatterns = [
    path("api/v1/", include("api.urls")),
    path("console/", include("console.urls")),
    path("healthz", healthz, name="healthz"),
    path("", home, name="home"),
]
