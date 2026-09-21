"""Celery taskovi engine-a. Canon §11.1–11.3, Behaviour v0.1 §18.

    behaviour.scan_due   beat, 30 s, queue persona.scheduled
    behaviour.wake       jedno buđenje; queue po razlogu (WAKE_QUEUE)

`wake` se zakazuje sa `eta = due_at`: scan gleda 90 s unapred, a persona
ne sme da se probudi pre svog prozora.
"""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from api.context import bind
from apps.behaviour import scheduler, service
from apps.behaviour.models import WorldEvent
from apps.personas.models import Persona
from common import enums as E
from config.celery import app


#: Canon §11.3 — prioritet unutar queue-a je Celery 0–9, mapiran iz §11.2.
def _celery_priority(reason: E.WakePriority) -> int:
    return min(9, E.WAKE_PRIORITY_VALUE[reason] // 11)


def dispatch(persona_public_id: str, reason: E.WakePriority, *, wake_key: str,
             not_before: datetime | None = None, event_id: str | None = None,
             relevance: float | None = None) -> None:
    wake_persona.apply_async(
        kwargs={"persona_id": persona_public_id, "reason": reason.value, "wake_key": wake_key,
                "not_before": not_before.isoformat() if not_before else None,
                "event_id": event_id, "relevance": relevance},
        queue=E.WAKE_QUEUE[reason].value,
        priority=_celery_priority(reason),
        eta=not_before if not_before and not_before > timezone.now() else None,
    )


@app.task(name="behaviour.scan_due")
def scan_due() -> int:
    with bind(actor_id="service:scheduler"):
        due = scheduler.scan_due(timezone.now())
        for d in due:
            dispatch(d.persona_public_id, d.priority, wake_key=d.wake_key, not_before=d.due_at)
    return len(due)


@app.task(name="behaviour.wake", bind=True, max_retries=3, default_retry_delay=10)
def wake_persona(self, persona_id: str, reason: str, wake_key: str,
                 not_before: str | None = None, event_id: str | None = None,
                 relevance: float | None = None) -> str | None:
    persona = Persona.objects.filter(public_id=persona_id).first()
    if persona is None:
        return None
    now = timezone.now()
    if not_before:
        now = max(now, datetime.fromisoformat(not_before))
    event = WorldEvent.objects.filter(public_id=event_id).first() if event_id else None
    with bind(actor_id="service:scheduler"):
        run = service.wake(persona, E.WakePriority(reason), now=now, wake_key=wake_key,
                           event=event, relevance=relevance)
    return run.public_id
