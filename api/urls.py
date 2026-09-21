"""Rute pod `/api/v1/`. Canon §8.1–8.2 — putanje su iz kanonske liste."""

from __future__ import annotations

from django.urls import path

from api.views.ops import AuditListView
from api.views.orchestration import ActionDetailView, ActionPolicyTraceView, RunDetailView
from api.views.personas import PersonaDetailView, PersonaListView, PersonaSnapshotView

urlpatterns = [
    path("personas", PersonaListView.as_view(), name="personas"),
    path("personas/<str:public_id>", PersonaDetailView.as_view(), name="persona-detail"),
    path("personas/<str:public_id>/snapshot", PersonaSnapshotView.as_view(),
         name="persona-snapshot"),
    path("runs/<str:run_id>", RunDetailView.as_view(), name="run-detail"),
    path("actions/<str:action_id>", ActionDetailView.as_view(), name="action-detail"),
    path("actions/<str:action_id>/policy-trace", ActionPolicyTraceView.as_view(),
         name="action-policy-trace"),
    path("audit", AuditListView.as_view(), name="audit"),
]
