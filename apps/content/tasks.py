"""Celery taskovi sadržaja. ADR-0009.

    content.draft_for_run(run_id)   queue `persona.scheduled` — nacrt posle buđenja
"""

from __future__ import annotations

from apps.content.planner import draft_for_run_now
from config.celery import app


@app.task(name="content.draft_for_run")
def draft_for_run(run_pk: str) -> None:
    draft_for_run_now(run_pk)
