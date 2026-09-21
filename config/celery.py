"""Celery aplikacija. Canon §11.3 — deset queue-ova i ni jedan više."""

from __future__ import annotations

import os

from celery import Celery
from kombu import Queue

from common.enums import QueueName

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("persona_os")
app.config_from_object("django.conf:settings", namespace="CELERY")

#: Canon §11.3 — domen bira queue, prioritet je atribut poruke.
app.conf.task_queues = tuple(Queue(q.value) for q in QueueName)

app.autodiscover_tasks()

#: Task → queue. Ne oslanjamo se na podrazumevani `celery` queue: on nije
#: među deset kanonskih i nijedan worker ga ne sluša, pa bi task tiho čekao.
app.conf.task_routes = {
    "observability.publish_outbox": {"queue": QueueName.CONTROL.value},
}
app.conf.task_default_queue = QueueName.MAINTENANCE.value

#: Periodični krug objave outbox-a (ADR-0004). Glavni okidač je `on_commit`
#: posle svakog eventa; ovaj krug pokupi ono što je ostalo ako Redis u tom
#: trenutku nije odgovarao. 30 s prati beat iz Canon §11.1.
app.conf.beat_schedule = {
    "publish-outbox": {
        "task": "observability.publish_outbox",
        "schedule": 30.0,
        "options": {"queue": QueueName.CONTROL.value},
    },
}
