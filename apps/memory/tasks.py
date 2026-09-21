"""Celery taskovi memorije. Memory v0.1 §14; Canon §11.3.

    memory.maintenance   beat, svaki sat, queue `memory`

Jedan task po satu umesto pet rasporeda: za svaku personu proveri se
lokalni sat. Istek radne memorije ide svaki put; konsolidacija juče i
bleđenje idu kad je kod persone 03:xx (Memory v0.1 §9.1: 02:00–04:00).
Konsolidacija je idempotentna (`source_event_id`), pa ponovljen sat ne
pravi drugi dnevni zapis.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from api.context import bind
from apps.behaviour.clock import local
from apps.memory import lifecycle
from apps.personas.models import Persona
from common import enums as E
from config.celery import app

CONSOLIDATION_LOCAL_HOUR = 3


@app.task(name="memory.maintenance")
def maintenance() -> dict[str, int]:
    now = timezone.now()
    stats = {"expired": 0, "consolidated": 0, "faded": 0}
    with bind(actor_id="service:memory"):
        for p in Persona.objects.exclude(status=E.PersonaStatus.ARCHIVED.value):
            stats["expired"] += lifecycle.expire_working(p, now)
            loc = local(now, p.timezone)
            if loc.hour == CONSOLIDATION_LOCAL_HOUR:
                if lifecycle.consolidate_day(p, (loc - timedelta(days=1)).date(), now=now):
                    stats["consolidated"] += 1
                stats["faded"] += lifecycle.apply_decay(p, now)
    return stats
