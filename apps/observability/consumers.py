"""Potrošači eventa koje drži `observability`.

Za sada jedan: svaki event iz kataloga dobija red u audit-u. To je ono što
čini lanac `proposed → decision → attempt → outcome` iz Canon §16.5 vidljivim
na jednom mestu, bez obzira na to koji domen je event emitovao.
"""

from __future__ import annotations

from typing import Any

from api import audit
from api.context import bind
from apps.observability.bus import consumer


@consumer("observability.audit", "*")
def audit_every_event(envelope: dict[str, Any]) -> None:
    from apps.personas.models import Persona

    persona = None
    if envelope.get("persona_id"):
        persona = Persona.objects.filter(public_id=envelope["persona_id"]).first()
    # Audit red nosi trace_id eventa, ne trace_id kruga objave — inače bi se
    # lanac prekinuo baš na mestu gde event prelazi iz jednog domena u drugi.
    with bind(actor_id="service:event-bus", trace_id=envelope["trace_id"]):
        audit.record(
            f"event.{envelope['event_type']}",
            persona=persona,
            details={
                "event_id": envelope["event_id"],
                "run_id": envelope.get("run_id"),
                "causation_id": envelope.get("causation_id"),
            },
        )
