"""Sadržaj prati akciju objave (ADR-0009). At-least-once, zato idempotentno."""

from __future__ import annotations

from typing import Any

from api.context import bind
from apps.observability.bus import consumer


@consumer("content.publication_sync", "approval.resolved", "action.queued",
          "action.succeeded", "action.failed", "action.blocked")
def sync_publication(envelope: dict[str, Any]) -> None:
    from apps.content.models import Publication
    from apps.content.service import sync_from_action
    from apps.orchestration.models import Action
    from apps.policy.models import ApprovalRequest

    payload = envelope.get("payload") or {}
    action = None
    if payload.get("action_id"):
        action = Action.objects.filter(public_id=payload["action_id"]).first()
    elif payload.get("approval_id"):
        ap = ApprovalRequest.objects.filter(public_id=payload["approval_id"]).select_related(
            "action").first()
        action = ap.action if ap else None
    if action is None or not Publication.objects.filter(action=action).exists():
        return
    with bind(actor_id="service:content", trace_id=envelope["trace_id"]):
        sync_from_action(action)
