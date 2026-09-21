"""Celery taskovi policy-ja. Canon §11.3, §15.2.

    policy.expire_approvals   beat, 60 s, queue `approval`
"""

from __future__ import annotations

from api.context import bind
from apps.policy import service
from config.celery import app


@app.task(name="policy.expire_approvals")
def expire_approvals() -> int:
    with bind(actor_id="service:policy"):
        return service.expire_approvals()
