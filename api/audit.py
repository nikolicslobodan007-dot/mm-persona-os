"""Upis u audit. Canon §16.5 — `audit_completeness = 100%`.

Svaki write endpoint zove `record()` unutar iste transakcije kao i sama
izmena: ako izmena prođe a audit ne, transakcija pada cela. Tako audit
ne može da „zaostane" za stanjem.

Ugovor API v0.1 §22 traži `before_hash` i `after_hash`. Čuvaju se u
payload-u, a `payload_hash` je hash celog zapisa — izmena bilo kog polja
posle upisa se vidi kao nepodudaranje.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from django.utils import timezone

from api.context import current
from common import enums as E

log = logging.getLogger("persona.audit")

#: Ključevi koji se nikada ne upisuju, ni kada ih pozivalac greškom pošalje.
#: Canon §17 i ugovor v0.1 §22: tajne ne idu ni u log ni u audit.
_SECRET_KEYS = frozenset(
    {"password", "token", "secret", "credential", "api_key", "authorization", "cookie"}
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=str)


def sha256_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[uklonjeno]" if any(s in k.lower() for s in _SECRET_KEYS) else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def record(
    event_key: str,
    *,
    severity: E.AuditSeverity = E.AuditSeverity.INFO,
    persona=None,
    action=None,
    run=None,
    before: Any = None,
    after: Any = None,
    details: dict[str, Any] | None = None,
):
    """Upisuje jedan `AuditEvent` i vraća ga."""
    from apps.observability.models import AuditEvent

    ctx = current()
    occurred_at = timezone.now()
    payload: dict[str, Any] = {
        "declared_actor": ctx.actor_id,
        "request_id": ctx.request_id,
        "details": _scrub(details or {}),
    }
    if before is not None:
        payload["before_hash"] = sha256_of(before)
    if after is not None:
        payload["after_hash"] = sha256_of(after)

    row = AuditEvent(
        occurred_at=occurred_at,
        severity=E.AuditSeverity(severity).value,
        event_key=event_key,
        persona=persona,
        action=action,
        run=run,
        actor_ref=ctx.principal or ctx.actor_id,
        trace_id=ctx.trace_id,
        payload=payload,
    )
    row.payload_hash = sha256_of(
        {
            "occurred_at": occurred_at.isoformat(),
            "event_key": event_key,
            "actor_ref": row.actor_ref,
            "persona": getattr(persona, "public_id", None),
            "payload": payload,
        }
    )
    row.save()
    log.info(
        "audit %s actor=%s persona=%s trace_id=%s",
        event_key, row.actor_ref, getattr(persona, "public_id", "-"), ctx.trace_id,
    )
    return row
