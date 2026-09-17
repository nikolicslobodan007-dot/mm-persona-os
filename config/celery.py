"""Celery aplikacija. Canon §11.3 — deset queue-ova i ni jedan više."""

from __future__ import annotations

import os

from celery import Celery

from common.enums import QueueName

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("persona_os")
app.config_from_object("django.conf:settings", namespace="CELERY")

#: Canon §11.3 — domen bira queue, prioritet je atribut poruke.
app.conf.task_queues = tuple(q.value for q in QueueName)

app.autodiscover_tasks()
