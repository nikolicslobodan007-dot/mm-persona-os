"""Celery task za objavu outbox-a. Queue `control` (Canon §11.3)."""

from __future__ import annotations

from config.celery import app


@app.task(name="observability.publish_outbox", ignore_result=True)
def publish_outbox() -> dict[str, int]:
    from apps.observability.bus import publish_pending

    return publish_pending()
