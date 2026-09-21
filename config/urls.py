"""Canon §8.1 — sve pod /api/v1/. Van toga samo `/healthz` i početna strana."""

from django.urls import include, path

from api.views.ops import healthz, home

urlpatterns = [
    path("api/v1/", include("api.urls")),
    path("healthz", healthz, name="healthz"),
    path("", home, name="home"),
]
