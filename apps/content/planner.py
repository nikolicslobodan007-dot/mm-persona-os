"""Most između buđenja i sadržaja (ADR-0009). Bez Celery uvoza na vrhu."""

from __future__ import annotations

import logging

from django.conf import settings

from api.context import bind

log = logging.getLogger(__name__)


def draft_for_run_now(run_pk) -> None:
    from apps.content.service import plan_post_for_run
    from apps.orchestration.models import AgentRun

    run = AgentRun.objects.select_related("persona", "trigger_event").filter(pk=run_pk).first()
    if run is None:
        return
    trace = run.trace_id.hex if run.trace_id else None
    with bind(actor_id="service:planner", trace_id=trace):
        plan_post_for_run(run)


def schedule_draft(run_pk) -> None:
    """Poziva se posle commit-a buđenja. Nacrt nikad ne sme da obori buđenje."""
    if not getattr(settings, "CONTENT_AUTODRAFT", True):
        return
    try:
        if getattr(settings, "CONTENT_ASYNC", False):
            from apps.content.tasks import draft_for_run

            draft_for_run.apply_async(args=[str(run_pk)], queue="persona.scheduled")
        else:
            draft_for_run_now(run_pk)
    except Exception:  # noqa: BLE001
        log.exception("nacrt za run %s nije napravljen", run_pk)
