"""Action Gateway — jedina kapija ka izvršenju. Canon §6.2, §9.1, §12.6, §15.3.

    contract = authorize(action)   # ili GatewayRefused

F6 adapteri (browser, mail, kanali) smeju da izvrše SAMO ono što im vrati
`authorize()`. Ovde se, neposredno pre izvršenja, ponovo proverava sve što
se moglo promeniti posle odluke (Policy v0.1 §12, §19.1):

  - akcija je QUEUED (ili RETRY_WAIT) i ima odluku ALLOW koja nije istekla;
  - sadržaj je isti kao u trenutku odluke (hash) — izmena traži novu odluku;
  - ako je bilo odobrenje: važi, nije opozvano i vezano je za TAJ hash;
  - nijedan kill-switch u opsegu nije aktivan (kill-switch pobeđuje raniji ALLOW);
  - persona nije pauzirana ni suspendovana;
  - kanal ima postavljenu AI oznaku gde je obavezna.

`dry_run` je True kad god spoljni efekat ne sme da nastane: globalni prekidač
`GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`, persona u SIMULATION/SHADOW, ili
interna akcija. Adapter sa `dry_run=True` ne dodiruje spoljni sistem (Behaviour
v0.1 §24). Do GO odluke prekidač je isključen — sve je `dry_run`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.orchestration.models import Action
from apps.policy import config, engine
from apps.policy.service import _block, _input_hash, _queue_for, active_kill_switches
from common import enums as E

DENIED = E.ExecutionOutcome.DENIED_BY_POLICY
_LIVE_ENVIRONMENTS = frozenset({E.RuntimeEnvironment.CONTROLLED_LIVE, E.RuntimeEnvironment.LIVE})
_LABEL_OK = frozenset({E.DisclosureLabelStatus.SET.value,
                       E.DisclosureLabelStatus.NOT_REQUIRED.value})


class GatewayRefused(Exception):
    def __init__(self, outcome: E.ExecutionOutcome, reason_code: str):
        super().__init__(f"{outcome.value}: {reason_code}")
        self.outcome, self.reason_code = outcome, reason_code


def _refuse(action: Action, outcome: E.ExecutionOutcome, reason: str, *,
            block: bool = True) -> GatewayRefused:
    """Blokiranje se upisuje i ostaje — zato se izuzetak baca tek POSLE commit-a."""
    if block:
        _block(action, outcome.value, reason)
    return GatewayRefused(outcome, reason)


def external_live(action: Action) -> bool:
    """Sme li spoljni efekat da nastane: globalni prekidač I persona u živom okruženju."""
    return bool(getattr(settings, "GLOBAL_EXTERNAL_ACTIONS_ENABLED", False)
                and E.RuntimeEnvironment(action.persona.runtime_environment)
                in _LIVE_ENVIRONMENTS)


def authorize(action: Action, *, now: datetime | None = None) -> dict[str, Any]:
    result = _authorize(action, now or timezone.now())
    if isinstance(result, GatewayRefused):
        raise result
    return result


def _authorize(action: Action, now: datetime) -> dict[str, Any] | GatewayRefused:
    with transaction.atomic():
        action = Action.objects.select_for_update(of=("self",)).select_related(
            "persona", "policy_decision", "channel_account", "run").get(pk=action.pk)
        if action.status not in (E.ActionStatus.QUEUED.value, E.ActionStatus.RETRY_WAIT.value):
            return _refuse(action, DENIED, "NOT_QUEUED", block=False)
        d = action.policy_decision
        if d is None or d.effect != E.PolicyEffect.ALLOW.value:
            return _refuse(action, DENIED, "NO_VALID_DECISION")
        if d.expires_at and now >= d.expires_at:
            return _refuse(action, DENIED, "DECISION_EXPIRED", block=False)
        from apps.policy.service import content_hash

        if content_hash(action.input_json) != action.content_hash or \
                _input_hash(action) != d.context_hash:
            return _refuse(action, DENIED, "PAYLOAD_CHANGED")

        approval = action.approvals.order_by("-created_at").first()
        if approval is not None:
            if approval.status not in (E.ApprovalStatus.APPROVED.value,
                                       E.ApprovalStatus.APPROVED_WITH_CHANGES.value):
                return _refuse(action, DENIED, "APPROVAL_NOT_VALID")
            if approval.payload_hash != action.content_hash:
                return _refuse(action, DENIED, "APPROVAL_HASH_MISMATCH")
            if approval.revoked_at or now >= approval.expires_at:
                return _refuse(action, DENIED, "APPROVAL_EXPIRED")
        elif E.PolicyReason.APPROVED.value in (d.reason_codes or []):
            return _refuse(action, DENIED, "APPROVAL_MISSING")

        caps = config.action_types().get(action.action_type, [])
        channel = action.channel_account
        ctx = engine.Context(
            persona_id=action.persona.public_id,
            persona_status=E.PersonaStatus(action.persona.status),
            action_type=action.action_type, payload={}, now=now,
            channel=engine.Channel(str(channel.id), channel.channel_type, channel.status,
                                   channel.disclosure_label_status, frozenset())
            if channel else None,
            kill_switches=active_kill_switches(),
        )
        if engine._scope_hits(ctx, caps):
            return _refuse(action, DENIED,
                    E.PolicyReason.KILL_SWITCH_ACTIVE.value)
        if action.persona.status not in (E.PersonaStatus.READY.value,
                                         E.PersonaStatus.ACTIVE.value):
            return _refuse(action, DENIED,
                    E.PolicyReason.PERSONA_NOT_OPERATIONAL.value)
        needs_label = any((config.capability(c) or {}).get("requires_disclosure_label")
                          for c in caps)
        if needs_label and (channel is None or channel.disclosure_label_status not in _LABEL_OK):
            return _refuse(action, E.ExecutionOutcome.DISCLOSURE_MISSING,
                    E.OUTCOME_REASON_CODE[E.ExecutionOutcome.DISCLOSURE_MISSING])

        internal = action.action_type in E.INTERNAL_ACTION_TYPES
        live = external_live(action)
        return {
            "action_id": action.public_id,
            "persona_id": action.persona.public_id,
            "action_type": action.action_type,
            "policy_decision_id": d.public_id,
            "approval_id": approval.public_id if approval else None,
            "approval_expires_at": approval.expires_at.isoformat().replace("+00:00", "Z")
            if approval else None,
            "idempotency_key": f"sha256:{action.idempotency_key}",
            "trace_id": action.trace_id.hex if action.trace_id else None,
            "deadline_at": action.deadline_at.isoformat().replace("+00:00", "Z")
            if action.deadline_at else None,
            "identity_vehicle": channel.identity_vehicle if channel else None,
            "disclosure_label_status": channel.disclosure_label_status if channel else None,
            "queue": _queue_for(action.action_type).value,
            "obligations": d.obligations or [],
            "execution_constraints": {
                "max_attempts": action.max_attempts,
                "evidence_level": E.EvidenceLevel.RESPONSE_ONLY.value,
                **(d.constraints or {}),
            },
            "dry_run": internal or not live,
        }
