"""Celery taskovi kanala. ADR-0015.

    channels.mail_poll      beat 120 s, `mail` — pristigla pošta persona (IMAP)
"""

from __future__ import annotations

from api.context import bind
from apps.channels import mailbox
from config.celery import app


@app.task(name="channels.mail_poll")
def mail_poll() -> dict:
    with bind(actor_id="service:mail-poll"):
        return mailbox.poll_all()
