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
    "behaviour.scan_due": {"queue": QueueName.PERSONA_SCHEDULED.value},
    "memory.maintenance": {"queue": QueueName.MEMORY.value},
    "policy.expire_approvals": {"queue": QueueName.APPROVAL.value},
    # runtime.execute se šalje eksplicitno na queue posla (browser/mail/channel).
    "runtime.dispatch_due": {"queue": QueueName.CONTROL.value},
    "content.draft_for_run": {"queue": QueueName.PERSONA_SCHEDULED.value},
    "runtime.reap_leases": {"queue": QueueName.MAINTENANCE.value},
    "runtime.reconcile": {"queue": QueueName.MAINTENANCE.value},
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
    # Canon §11.1 — due resolver svakih 30 s, lookahead 90 s.
    "scan-due-personas": {
        "task": "behaviour.scan_due",
        "schedule": 30.0,
        "options": {"queue": QueueName.PERSONA_SCHEDULED.value, "expires": 25},
    },
    # Memory v0.1 §14 — istek radne memorije; konsolidacija i bleđenje u 03h lokalno.
    "memory-maintenance": {
        "task": "memory.maintenance",
        "schedule": 3600.0,
        "options": {"queue": QueueName.MEMORY.value, "expires": 3000},
    },
    # Canon §15.2 — istek odobrenja (najkraći TTL je 30 min, pa je minut dovoljan).
    "expire-approvals": {
        "task": "policy.expire_approvals",
        "schedule": 60.0,
        "options": {"queue": QueueName.APPROVAL.value, "expires": 50},
    },
    # F6 (ADR-0008) — izvršenje, leasing (Canon §12.3), reconcile.
    "runtime-dispatch-due": {
        "task": "runtime.dispatch_due",
        "schedule": 15.0,
        "options": {"queue": QueueName.CONTROL.value, "expires": 12},
    },
    "runtime-reap-leases": {
        "task": "runtime.reap_leases",
        "schedule": 30.0,
        "options": {"queue": QueueName.MAINTENANCE.value, "expires": 25},
    },
    "runtime-reconcile": {
        "task": "runtime.reconcile",
        "schedule": 60.0,
        "options": {"queue": QueueName.MAINTENANCE.value, "expires": 50},
    },
}
