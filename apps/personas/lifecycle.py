"""Status persone — ko sme koji prelaz. Canon §3.1 · ADR-0011.

Status se ne menja kroz PATCH (nema sopstveni tok odobrenja tamo). Ovde je
jedini put, sa tabelom prelaza, obaveznim razlogom i audit zapisom.

`PAUSED` je operativna odluka i vraća se jednim klikom. `SUSPENDED` je
bezbednosna i povratak traži Trust & Safety (§3.1). `ARCHIVED` je trajan.
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from api import audit
from apps.personas.models import Persona
from common import enums as E

S = E.PersonaStatus
R = E.Role
_OPS = frozenset({R.OPERATOR, R.PERSONA_MANAGER, R.SYSTEM_ADMIN})
_PM = frozenset({R.PERSONA_MANAGER, R.SYSTEM_ADMIN})
_TS = frozenset({R.TRUST_SAFETY})

#: (od, do) → uloge koje smeju. Sve što nije ovde je zabranjeno.
TRANSITIONS: dict[tuple[S, S], frozenset[E.Role]] = {
    (S.DRAFT, S.READY): _PM,
    (S.READY, S.ACTIVE): _OPS,
    (S.ACTIVE, S.PAUSED): _OPS | {R.RUNTIME_ADMIN, R.TRUST_SAFETY},
    (S.PAUSED, S.ACTIVE): _OPS,
    (S.READY, S.PAUSED): _OPS,
    (S.DEGRADED, S.ACTIVE): _TS,
    (S.SUSPENDED, S.READY): _TS,
    (S.ACTIVE, S.SUSPENDED): _TS,
    (S.READY, S.ARCHIVED): frozenset({R.SYSTEM_ADMIN}),
    (S.PAUSED, S.ARCHIVED): frozenset({R.SYSTEM_ADMIN}),
    (S.SUSPENDED, S.ARCHIVED): frozenset({R.SYSTEM_ADMIN}),
    (S.DRAFT, S.ARCHIVED): frozenset({R.SYSTEM_ADMIN}),
}


class LifecycleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def allowed_targets(persona: Persona, roles: set[E.Role]) -> list[S]:
    now = S(persona.status)
    return [to for (frm, to), who in TRANSITIONS.items() if frm == now and roles & who]


def _can_activate(persona: Persona) -> str | None:
    from apps.behaviour.models import BehaviourState, RoutineTemplate

    if not BehaviourState.objects.filter(persona=persona).exists():
        return "Persona nema stanje ponašanja (seed nije završen)."
    if not RoutineTemplate.objects.filter(persona=persona, is_enabled=True).exists():
        return "Persona nema uključenu rutinu — scheduler ne bi imao kad da je probudi."
    return None


def change_status(persona: Persona, to: S, *, actor: str, roles: set[E.Role],
                  reason: str, now: datetime | None = None) -> Persona:
    now = now or timezone.now()
    reason = (reason or "").strip()
    if not reason:
        raise LifecycleError("VALIDATION_ERROR", "Promena statusa traži razlog.")
    with transaction.atomic():
        p = Persona.objects.select_for_update().get(pk=persona.pk)
        frm = S(p.status)
        who = TRANSITIONS.get((frm, to))
        if who is None:
            raise LifecycleError("VALIDATION_ERROR", f"Prelaz {frm.value} → {to.value} ne postoji.")
        if not roles & who:
            raise LifecycleError("FORBIDDEN",
                                 f"{frm.value} → {to.value} smeju: "
                                 + ", ".join(sorted(r.value for r in who)))
        if to == S.ACTIVE and (why := _can_activate(p)):
            raise LifecycleError("VALIDATION_ERROR", why)
        fields = {"status": to.value, "version": F("version") + 1}
        if to == S.ACTIVE and p.activated_at is None:
            fields["activated_at"] = now
        if to == S.ARCHIVED:
            fields["archived_at"] = now
        Persona.objects.filter(pk=p.pk).update(**fields)
        if to == S.ACTIVE:
            # Probudi je uskoro, ne u trenutku kada je stanje poslednji put računato.
            from django.db.models import Q

            from apps.behaviour.models import BehaviourState

            BehaviourState.objects.filter(Q(next_wake_at__lt=now) | Q(next_wake_at__isnull=True),
                                          persona=p).update(next_wake_at=now)
        p.refresh_from_db()
        audit.record("persona.status.changed", persona=p, severity=E.AuditSeverity.WARNING,
                      before={"status": frm.value}, after={"status": to.value},
                      details={"reason": reason, "actor": actor})
    return p
