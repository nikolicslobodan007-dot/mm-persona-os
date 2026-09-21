"""Circuit breaker po paru (adapter, nalog). Canon §12.5 · ADR-0008."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import IntegrityError, transaction

from apps.runtime.models import CircuitBreaker
from common import enums as E

B = E.BreakerState
#: Ishodi koji se broje kao greška kanala (ne naše odbijanje, ne naš tempo).
FAILURE_REASONS = frozenset({"HTTP_429", "HTTP_5XX", "NETWORK", "TIMEOUT"})


def _get(adapter_key: str, account) -> CircuitBreaker:
    b = CircuitBreaker.objects.filter(adapter_key=adapter_key, account=account).order_by(
        "created_at").first()
    if b is None:
        try:
            with transaction.atomic():
                b = CircuitBreaker.objects.create(adapter_key=adapter_key, account=account)
        except IntegrityError:
            b = CircuitBreaker.objects.get(adapter_key=adapter_key, account=account)
    return CircuitBreaker.objects.select_for_update().get(pk=b.pk)


def allow(adapter_key: str, account, now: datetime) -> tuple[bool, datetime | None]:
    """Da li sme novi pokušaj. Poziva se unutar transakcije."""
    b = _get(adapter_key, account)
    if b.state == B.OPEN.value:
        reopen = b.opened_at + timedelta(seconds=E.BREAKER_COOLDOWN_SECONDS)
        if now < reopen:
            return False, reopen
        b.state, b.probes = B.HALF_OPEN.value, 0
    if b.state == B.HALF_OPEN.value:
        if b.probes >= E.BREAKER_MAX_PROBES:
            return False, now + timedelta(seconds=30)
        b.probes += 1
    b.save(update_fields=["state", "probes", "updated_at"])
    return True, None


def is_failure(outcome: E.ExecutionOutcome, reason: str) -> bool:
    return outcome == E.ExecutionOutcome.UNKNOWN_EFFECT or (
        outcome == E.ExecutionOutcome.RETRYABLE_ERROR and reason in FAILURE_REASONS)


def record(adapter_key: str, account, *, ok: bool, now: datetime, persona=None) -> str:
    """Upisuje ishod; vraća novo stanje. Otvaranje otvara SEV3 incident."""
    b = _get(adapter_key, account)
    window = now - timedelta(seconds=E.BREAKER_WINDOW_SECONDS)
    fails = [t for t in (b.failures or []) if datetime.fromisoformat(t) >= window]
    opened = False
    if ok:
        if b.state == B.HALF_OPEN.value:
            b.state, fails, b.probes = B.CLOSED.value, [], 0
    else:
        fails.append(now.isoformat())
        if b.state == B.HALF_OPEN.value or (b.state == B.CLOSED.value
                                             and len(fails) >= E.BREAKER_FAILURES):
            b.state, b.opened_at, b.probes, opened = B.OPEN.value, now, 0, True
    b.failures = fails
    b.save(update_fields=["state", "failures", "opened_at", "probes", "updated_at"])
    if opened:
        from apps.policy.service import open_incident

        open_incident(E.IncidentSeverity.SEV3, "circuit_breaker",
                      f"Breaker otvoren: {adapter_key}"
                      f"{' / ' + account.handle if account else ''}",
                      persona=persona, reason_code="BREAKER_OPEN", now=now)
    return b.state
