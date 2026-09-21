"""Event bus preko outbox-a. Canon §7, ADR-0004.

    emit()            — u transakciji izmene: validira envelope šemom i upisuje outbox
    publish_pending() — posle commit-a: isporučuje potrošačima, označava objavljeno
    consumer()        — dekorator koji registruje potrošača za tipove eventa

Zašto outbox a ne direktno slanje u Redis: slanje posle commit-a može da se
izgubi ako proces padne između, a slanje pre commit-a objavljuje event za
promenu koja možda neće preživeti. Upis u istu transakciju uklanja oba
slučaja — event postoji ako i samo ako postoji i promena.

Isporuka je at-least-once (Canon §7.1). Potrošač koji je već obradio event
ne radi ponovo, jer `EventDelivery(consumer, event_id)` ne može da se upiše
dvaput. Ako jedan potrošač padne, event ostaje PENDING i sledeći krug ga
nudi ponovo — ali samo onima koji ga još nisu obradili.
"""

from __future__ import annotations

import json
import logging
import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jsonschema
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from api.context import current
from common import enums as E
from common.events import EventEnvelope

log = logging.getLogger("persona.events")

#: Posle ovoliko neuspelih krugova event ide u DEAD i traži čoveka.
MAX_ATTEMPTS = 10

Handler = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class Consumer:
    name: str
    event_types: frozenset[str]
    handler: Handler


_REGISTRY: dict[str, Consumer] = {}


class EventSchemaError(ValueError):
    """Event nije u katalogu ili ne prolazi svoju šemu (Canon §7.3)."""


def consumer(name: str, *event_types: str):
    """Registruje potrošača. `"*"` znači svi tipovi iz kataloga."""

    def decorate(fn: Handler) -> Handler:
        if name in _REGISTRY and _REGISTRY[name].handler is not fn:
            raise ValueError(f"potrošač {name!r} je već registrovan")
        _REGISTRY[name] = Consumer(name, frozenset(event_types), fn)
        return fn

    return decorate


def registered() -> dict[str, Consumer]:
    return dict(_REGISTRY)


def consumers_for(event_type: str) -> list[Consumer]:
    return [c for c in _REGISTRY.values() if _wants(c, event_type)]


def unregister(name: str) -> None:
    """Samo za testove — u radu se potrošači ne odjavljuju."""
    _REGISTRY.pop(name, None)


# ---------------------------------------------------------------- šeme §7.3


def _schema_dir() -> pathlib.Path:
    return pathlib.Path(settings.BASE_DIR) / "schemas" / "events"


@lru_cache(maxsize=64)
def _validator(event_type: str, version: int) -> jsonschema.Draft202012Validator:
    path = _schema_dir() / event_type / f"{version}.json"
    if not path.exists():
        # Canon §7.3: nijedan producer ne sme emitovati event bez šeme u registru.
        raise EventSchemaError(f"nema šeme za {event_type} v{version} (Canon §7.3)")
    schema = json.loads(path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )


def validate(envelope: dict[str, Any]) -> None:
    validator = _validator(envelope["event_type"], envelope["event_version"])
    errors = sorted(validator.iter_errors(envelope), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(koren)"
        raise EventSchemaError(f"{envelope['event_type']}: {where}: {first.message}")


# ---------------------------------------------------------------- emit


def emit(
    event_type: str,
    payload: dict[str, Any],
    *,
    persona_id: str | None,
    run_id: str | None = None,
    causation_id: str | None = None,
    trace_id: str | None = None,
):
    """Upisuje event u outbox. Mora biti pozvano unutar `transaction.atomic()`.

    Van transakcije bi upis eventa i upis promene bili dva nezavisna commit-a
    — upravo ono što outbox postoji da spreči.
    """
    from apps.observability.models import EventOutbox

    if not connection.in_atomic_block:
        raise RuntimeError("emit() mora biti pozvan unutar transaction.atomic() (ADR-0004)")

    envelope = EventEnvelope(
        event_type=event_type,
        persona_id=persona_id,
        trace_id=trace_id or current().trace_id,
        payload=payload,
        run_id=run_id,
        causation_id=causation_id,
    ).to_dict()
    validate(envelope)

    row = EventOutbox.objects.create(
        event_id=envelope["event_id"],
        event_type=event_type,
        event_version=envelope["event_version"],
        persona_public_id=persona_id or "",
        envelope=envelope,
    )
    transaction.on_commit(_schedule_publish)
    return row


def _schedule_publish() -> None:
    """Posle commit-a: zamoli worker da objavi. Ako Redis ne odgovara,
    red ostaje PENDING i pokupiće ga periodični krug — ništa se ne gubi."""
    if getattr(settings, "EVENT_BUS_EAGER", False):
        publish_pending()
        return
    try:
        from apps.observability.tasks import publish_outbox

        publish_outbox.apply_async(queue=E.QueueName.CONTROL.value)
    except Exception:  # noqa: BLE001
        log.warning("publish_outbox nije zakazan; ostaje za periodični krug", exc_info=True)


# ---------------------------------------------------------------- isporuka


def deliver(c: Consumer, envelope: dict[str, Any]) -> bool:
    """Isporučuje jedan event jednom potrošaču. Vraća False ako je već obrađen."""
    from apps.observability.models import EventDelivery

    with transaction.atomic():
        try:
            with transaction.atomic():
                EventDelivery.objects.create(consumer=c.name, event_id=envelope["event_id"])
        except IntegrityError:
            return False
        c.handler(envelope)
    return True


def _wants(c: Consumer, event_type: str) -> bool:
    return "*" in c.event_types or event_type in c.event_types


def publish_pending(limit: int = 200) -> dict[str, int]:
    """Jedan krug objave. Više workera sme da radi paralelno — SKIP LOCKED."""
    from apps.observability.models import EventOutbox

    stats = {"published": 0, "failed": 0, "dead": 0}
    with transaction.atomic():
        rows = list(
            EventOutbox.objects.select_for_update(skip_locked=True)
            .filter(status=E.OutboxStatus.PENDING)
            .order_by("id")[:limit]
        )
        for row in rows:
            errors: list[str] = []
            for c in consumers_for(row.event_type):
                try:
                    deliver(c, row.envelope)
                except Exception as exc:  # noqa: BLE001
                    log.exception("potrošač %s pao na %s", c.name, row.event_id)
                    errors.append(f"{c.name}: {type(exc).__name__}: {exc}"[:500])
            row.attempts += 1
            if errors:
                row.last_error = "\n".join(errors)
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = E.OutboxStatus.DEAD
                    stats["dead"] += 1
                else:
                    stats["failed"] += 1
            else:
                row.status = E.OutboxStatus.PUBLISHED
                row.published_at = timezone.now()
                row.last_error = ""
                stats["published"] += 1
            row.save(update_fields=["attempts", "status", "published_at", "last_error"])
    return stats
