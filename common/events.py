"""Event envelope i kanonski katalog eventa — Canon v1.1, §7.

Isporuka je at-least-once; deduplikacija po `event_id` na strani potrošača.
Svi timestamp-ovi su UTC sa `Z` sufiksom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from common.ids import EntityKind, new_ulid

__all__ = [
    "EVENT_TYPES",
    "EVENT_OWNERS",
    "RUN_ID_OPTIONAL",
    "RETIRED_EVENT_TYPES",
    "EventEnvelope",
]

#: Canon §7.2 — 23 eventa. Oblik: `<domen>.<entitet>.<glagol u prošlom vremenu>`.
EVENT_OWNERS: dict[str, str] = {
    "world.event.created": "behaviour",
    "behaviour.state.recomputed": "behaviour",
    "persona.woken": "orchestration",
    "plan.created": "orchestration",
    "action.proposed": "orchestration",
    "policy.decision.created": "policy",
    "approval.requested": "policy",
    "approval.resolved": "policy",
    "action.queued": "orchestration",
    "runtime.execution.started": "runtime",
    "runtime.execution.finished": "runtime",
    "action.succeeded": "orchestration",
    "action.failed": "orchestration",
    "action.blocked": "orchestration",
    "memory.created": "memory",
    "memory.consolidated": "memory",
    "memory.contradiction_detected": "memory",
    "context.built": "memory",
    "trust.level.changed": "policy",
    "killswitch.activated": "policy",
    "killswitch.cleared": "policy",
    "policy.incident.opened": "policy",
    "cost.recorded": "observability",
}

EVENT_TYPES: tuple[str, ...] = tuple(EVENT_OWNERS)

#: Canon §7.1 — eventi koji mogu nastati van buđenja persone. `run_id` je tada null.
RUN_ID_OPTIONAL: frozenset[str] = frozenset(
    {
        "world.event.created",
        "killswitch.activated",
        "killswitch.cleared",
        "cost.recorded",
        "memory.consolidated",
    }
)

#: Canon §7.2 — imena koja su ukinuta. Lint ih odbija (tools/canon_lint.py).
RETIRED_EVENT_TYPES: dict[str, str] = {
    "policy.allowed": "policy.decision.created sa effect: ALLOW",
    "behaviour.recomputed": "behaviour.state.recomputed",
    "assertion.contradiction_detected": "memory.contradiction_detected",
    "analytics.recorded": "cost.recorded (ili metrika, ne event)",
}


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Canon §7.1.

    `trace_id` je uvek obavezan. `run_id` je obavezan za evente iz
    `orchestration`, `runtime` i `policy` domena koji nastaju unutar buđenja
    persone; za evente iz `RUN_ID_OPTIONAL` je None.
    """

    event_type: str
    persona_id: str | None
    trace_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    causation_id: str | None = None
    event_version: int = 1
    event_id: str = field(default_factory=lambda: f"EVT-{new_ulid()}")
    occurred_at: str = field(default_factory=_utc_now_z)

    def __post_init__(self) -> None:
        if self.event_type in RETIRED_EVENT_TYPES:
            raise ValueError(
                f"{self.event_type!r} je ukinuto, koristi "
                f"{RETIRED_EVENT_TYPES[self.event_type]!r} (Canon §7.2)"
            )
        if self.event_type not in EVENT_OWNERS:
            raise ValueError(
                f"{self.event_type!r} nije u kanonskom katalogu (Canon §7.2)"
            )
        if not self.trace_id:
            raise ValueError("trace_id je uvek obavezan (Canon §2.3)")
        if self.run_id is None and self.event_type not in RUN_ID_OPTIONAL:
            raise ValueError(
                f"run_id je obavezan za {self.event_type!r} (Canon §7.1)"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at,
            "persona_id": self.persona_id,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "causation_id": self.causation_id,
            "payload": self.payload,
        }
