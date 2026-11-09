"""Celery taskovi memorije. Memory v0.1 §14; Canon §11.3.

    memory.maintenance   beat, svaki sat, queue `memory`

Jedan task po satu umesto pet rasporeda: za svaku personu proveri se
lokalni sat. Istek radne memorije ide svaki put; konsolidacija juče, bleđenje i pečaćenje
ličnih zapisa idu kad je kod persone 03:xx (Memory v0.1 §9.1: 02:00–04:00), a
kaskada ka sektoru i firmi jednom dnevno u 04:xx UTC (ADR-0020).
Konsolidacija je idempotentna (`source_event_id`), pa ponovljen sat ne
pravi drugi dnevni zapis.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from api.context import bind
from apps.behaviour.clock import local
from apps.memory import lifecycle, sealing
from apps.personas.models import Persona
from common import enums as E
from config.celery import app

logger = logging.getLogger(__name__)

CONSOLIDATION_LOCAL_HOUR = 3
#: ADR-0020 — sektorsko i firmsko pečaćenje jednom dnevno, posle ličnih sažetaka.
CASCADE_UTC_HOUR = 4


@app.task(name="memory.maintenance")
def maintenance() -> dict[str, int]:
    now = timezone.now()
    stats = {"expired": 0, "consolidated": 0, "faded": 0, "sealed": 0}
    with bind(actor_id="service:memory"):
        for p in Persona.objects.exclude(status=E.PersonaStatus.ARCHIVED.value):
            stats["expired"] += lifecycle.expire_working(p, now)
            loc = local(now, p.timezone)
            if loc.hour == CONSOLIDATION_LOCAL_HOUR:
                if lifecycle.consolidate_day(p, (loc - timedelta(days=1)).date(), now=now):
                    stats["consolidated"] += 1
                stats["faded"] += lifecycle.apply_decay(p, now)
                stats["sealed"] += len(sealing.seal_persona(p, now=now))
        # Kaskada naviše ide jednom dnevno, po UTC-u, kad su lični sažeci gotovi.
        if now.hour == CASCADE_UTC_HOUR:
            up = sealing.seal_all(now=now)
            stats["sealed"] += up["sektor"] + up["firma"]
    return stats


@app.task(name="memory.github_signals_dnevno")
def github_signals_dnevno(najvise: int = 10, min_zvezdica: int = 50) -> str:
    """Dnevni autopilot: sakupi N novih GitHub Signals repoa + auto-uvoz.

    ADR-0074 granica: uvoz pokreće čovek. Ovde je to `user:slobodan` kao njegova
    STAJAĆA odluka (2026-11-09) — SLOBODNA se auto-uvozi kao upotrebljivo;
    NEPOZNATA/ZARAZNA/ZABRANJENA se beleže ali ostaju NEupotrebljivo (sistem
    pušta samo SLOBODNA) do njegovog pregleda. Beleženje svih spречava da se
    dnevni „top N" zaglavi i da se ponovo plaća destilacija.
    """
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("signali", auto=True, najvise=najvise,
                 min_zvezdica=min_zvezdica, stdout=out)
    izvestaj = out.getvalue()
    logger.info("github_signals_dnevno:\n%s", izvestaj[-1500:])
    preg = StringIO()
    call_command("signali", pregled=True, stdout=preg)
    logger.info("github_signals stanje:\n%s", preg.getvalue()[-1500:])
    redovi = izvestaj.strip().splitlines()
    return redovi[-1] if redovi else "nema izveštaja"
