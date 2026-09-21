"""Canon §8.1 — sve pod /api/v1/. Van toga samo `/healthz`."""

from django.urls import include, path

from api.views.ops import healthz

urlpatterns = [
    path("api/v1/", include("api.urls")),
    path("healthz", healthz, name="healthz"),
]
