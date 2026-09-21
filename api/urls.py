"""Rute pod `/api/v1/`. Canon §8.1–8.2 — putanje su iz kanonske liste."""

from __future__ import annotations

from django.urls import path

from api.views.behaviour import BehaviourTickView, PersonaTimelineView, PersonaWakeView
from api.views.content import (
    ContentItemDetailView,
    ContentItemsView,
    ContentScheduleView,
)
from api.views.memory import (
    ContextBuildView,
    MemoryCreateView,
    MemoryQueryView,
    MemorySupersedeView,
)
from api.views.ops import AuditListView
from api.views.orchestration import ActionDetailView, ActionPolicyTraceView, RunDetailView
from api.views.personas import PersonaDetailView, PersonaListView, PersonaSnapshotView
from api.views.policy import (
    ActionProposeView,
    ApprovalDecisionView,
    ApprovalListView,
    IncidentListView,
    KillSwitchView,
    PolicyEvaluateBatchView,
    PolicyEvaluateView,
    TrustChangeView,
)
from api.views.runtime import (
    ChannelAccountCapabilitiesView,
    ChannelAccountListView,
    OpsOverviewView,
    SuppressionView,
    unsubscribe,
)

urlpatterns = [
    path("personas", PersonaListView.as_view(), name="personas"),
    path("personas/<str:public_id>", PersonaDetailView.as_view(), name="persona-detail"),
    path("personas/<str:public_id>/snapshot", PersonaSnapshotView.as_view(),
         name="persona-snapshot"),
    path("personas/<str:public_id>/wake", PersonaWakeView.as_view(), name="persona-wake"),
    path("personas/<str:public_id>/behaviour/tick", BehaviourTickView.as_view(),
         name="persona-behaviour-tick"),
    path("ops/personas/<str:public_id>/timeline", PersonaTimelineView.as_view(),
         name="ops-persona-timeline"),
    path("personas/<str:public_id>/memories", MemoryCreateView.as_view(), name="memories"),
    path("personas/<str:public_id>/memories/query", MemoryQueryView.as_view(),
         name="memories-query"),
    path("context/build", ContextBuildView.as_view(), name="context-build"),
    path("memories/<str:memory_id>/supersede", MemorySupersedeView.as_view(),
         name="memory-supersede"),
    path("runs/<str:run_id>", RunDetailView.as_view(), name="run-detail"),
    path("actions/propose", ActionProposeView.as_view(), name="actions-propose"),
    path("actions/<str:action_id>", ActionDetailView.as_view(), name="action-detail"),
    path("actions/<str:action_id>/policy-trace", ActionPolicyTraceView.as_view(),
         name="action-policy-trace"),
    path("audit", AuditListView.as_view(), name="audit"),
    path("policy/evaluate", PolicyEvaluateView.as_view(), name="policy-evaluate"),
    path("policy/evaluate/batch", PolicyEvaluateBatchView.as_view(),
         name="policy-evaluate-batch"),
    path("policy/incidents", IncidentListView.as_view(), name="policy-incidents"),
    path("approvals", ApprovalListView.as_view(), name="approvals"),
    path("approvals/<str:approval_id>/decision", ApprovalDecisionView.as_view(),
         name="approval-decision"),
    path("personas/<str:public_id>/trust/change", TrustChangeView.as_view(),
         name="persona-trust-change"),
    path("kill-switches", KillSwitchView.as_view(), name="kill-switches"),
    # F7 (ADR-0009)
    path("content/items", ContentItemsView.as_view(), name="content-items"),
    path("content/items/<str:content_id>", ContentItemDetailView.as_view(),
         name="content-item-detail"),
    path("content/items/<str:content_id>/schedule", ContentScheduleView.as_view(),
         name="content-item-schedule"),
    # F6 (ADR-0008)
    path("channels/accounts", ChannelAccountListView.as_view(), name="channel-accounts"),
    path("channels/accounts/<str:account_id>/capabilities",
         ChannelAccountCapabilitiesView.as_view(), name="channel-account-capabilities"),
    path("ops/overview", OpsOverviewView.as_view(), name="ops-overview"),
    path("mail/suppressions", SuppressionView.as_view(), name="mail-suppressions"),
    path("mail/unsubscribe", unsubscribe, name="mail-unsubscribe"),
]
