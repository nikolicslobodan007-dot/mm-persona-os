"""Policy servis nad bazom: predlog, odluka, odobrenje, poverenje, stop, incident.
Canon §6.2–6.3, §9, §15; Policy v0.1 §7–§13.

Pravilo koje ovde ne sme da se prekrši (Canon §6.2):
    Nijedan spoljni efekat bez važeće `PolicyDecision` na `Action`.
Baza ga već sprovodi (CHECK na `orchestration_action`); ovaj modul je
jedini koji akciju prevodi u QUEUED.

Svaka operacija je jedna transakcija sa svojim eventima (outbox, ADR-0004):
ili postoji i promena i trag, ili ne postoji ništa.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from api import audit
from api.audit import canonical_json, sha256_of
from api.context import current
from apps.behaviour.clock import local
from apps.channels.models import ChannelAccount, ChannelCapability
from apps.observability import bus
from apps.orchestration.models import Action, AgentRun, PlanStep
from apps.personas.models import Persona
from apps.policy import config, engine
from apps.policy.models import (
    ApprovalRequest,
    CapabilityGrant,
    KillSwitch,
    PolicyDecision,
    PolicyIncident,
    PolicyRule,
    TrustState,
)
from common import enums as E
from common import ids as I

EVALUATOR_VERSION = "f5-1"
_OPEN = (E.ActionStatus.PROPOSED, E.ActionStatus.POLICY_CHECK,
         E.ActionStatus.APPROVAL_PENDING, E.ActionStatus.QUEUED, E.ActionStatus.RETRY_WAIT)
_EXPIRY_STATUS = {
    E.ApprovalClass.A1: E.ActionStatus.CANCELLED,  # nacrt ostaje, akcija otkazana
    E.ApprovalClass.A2: E.ActionStatus.EXPIRED,    # bez akcije
    E.ApprovalClass.A3: E.ActionStatus.BLOCKED,    # DENY
    E.ApprovalClass.A4: E.ActionStatus.BLOCKED,    # DENY + eskalacija
}


class PolicyError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.details = code, details or {}


# ---------------------------------------------------------------- pomoćno


def content_hash(payload: dict[str, Any]) -> str:
    return sha256_of(payload)


def idempotency_key(persona_id: str, action_type: str, target_ref: str, chash: str,
                    plan_step_id: str | None) -> str:
    """Canon §6.3 — sha256(persona | type | target | content | step)."""
    raw = "|".join([persona_id, action_type, target_ref or "", chash, plan_step_id or ""])
    return hashlib.sha256(raw.encode()).hexdigest()


def _input_hash(action: Action) -> str:
    return sha256_of({
        "persona": action.persona.public_id, "action_type": action.action_type,
        "target_ref": action.target_ref, "content_hash": action.content_hash,
        "channel_account": str(action.channel_account_id or ""),
        "policy_version": config.policy_version(),
    })


def _trace():
    import uuid

    return uuid.UUID(hex=current().trace_id)


def _run_id(action: Action) -> str | None:
    return action.run.public_id if action.run_id else None


def _queue_for(action_type: str) -> E.QueueName:
    if action_type.startswith("browser."):
        return E.QueueName.BROWSER
    if action_type.startswith("mail."):
        return E.QueueName.MAIL
    if action_type.startswith("channel."):
        return E.QueueName.CHANNEL
    return E.QueueName.MAINTENANCE


def active_kill_switches() -> list[tuple[str, str]]:
    return list(KillSwitch.objects.filter(is_active=True).values_list("scope", "target_ref"))


def _local_day_bounds(persona: Persona, now: datetime) -> tuple[datetime, datetime]:
    loc = local(now, persona.timezone)
    start = loc.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _counts(persona: Persona, action_type: str, now: datetime, exclude_pk=None) -> dict[str, int]:
    start, end = _local_day_bounds(persona, now)
    qs = Action.objects.filter(persona=persona, created_at__gte=start, created_at__lt=end,
                               status__in=[s.value for s in E.COUNTED_ACTION_STATUSES]
                               ).exclude(action_type__in=E.INTERNAL_ACTION_TYPES)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    rows = list(qs.values_list("action_type", "channel_account__channel_type"))
    out: dict[str, int] = {"total": len(rows)}
    for at, ch in rows:
        dim = E.ACTION_RATE_DIMENSION.get(at)
        if dim:
            out[dim] = out.get(dim, 0) + 1
        if at == "channel.post.create" and ch == E.ChannelType.X.value:
            out["x_posts"] = out.get("x_posts", 0) + 1
        out[f"type:{at}"] = out.get(f"type:{at}", 0) + 1
    return out


def _rules(now: datetime) -> list[engine.Rule]:
    out = []
    for r in PolicyRule.objects.filter(is_enabled=True, effective_from__lte=now).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=now)):
        out.append(engine.Rule(
            key=r.key, version=r.version, effect=E.PolicyEffect(r.effect), scope=r.scope,
            action_type=r.action_type or "", capability=r.capability or "",
            channel_type=r.channel_type or "",
            approval_class=E.ApprovalClass(r.approval_class) if r.approval_class else None,
            per_day=(r.rate_limit_json or {}).get("per_day"),
            prohibition_id=(r.condition_json or {}).get("prohibition_id"),
            is_hard=r.is_hard_prohibition,
        ))
    return out


def _channel_ctx(account: ChannelAccount | None) -> engine.Channel | None:
    if account is None:
        return None
    enabled = frozenset(ChannelCapability.objects.filter(
        account=account, is_enabled=True).values_list("capability", flat=True))
    return engine.Channel(id=str(account.id), channel_type=account.channel_type,
                          status=account.status,
                          disclosure_label_status=account.disclosure_label_status,
                          enabled_capabilities=enabled)


def trust_map(persona: Persona) -> dict[str, E.TrustLevel]:
    """Poverenje bez opsega — ono što motor pravila oduvek dobija.

    Redovi sa opsegom (ADR-0034) namerno se ne mešaju ovde: oni važe samo za
    kod i pitaju se kroz `trust_for()`, sa putanjom u ruci.
    """
    return {c: E.TrustLevel(lv) for c, lv in
            TrustState.objects.filter(persona=persona, scope="").values_list(
                "capability", "level")}


def normalize_path(path: str) -> str:
    """Putanja u obliku u kom se poredi: kose crte napred, bez vodeće tačke."""
    p = str(path).replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def path_is_protected(path: str) -> str | None:
    """Vraća zonu koja zabranjuje putanju, ili `None`.

    Ovo se pita **pre** poverenja i ne zavisi od nivoa: zaštićena zona se ne
    otvara podizanjem nivoa, nego samo ADR-om i ljudskom rukom (ADR-0034).
    """
    p = normalize_path(path)
    for zona in config.protected_paths():
        z = normalize_path(zona)
        if p == z.rstrip("/") or p.startswith(z if z.endswith("/") else z):
            return zona
    return None


def trust_for(persona: Persona, capability: str, path: str = "") -> E.TrustLevel:
    """Nivo poverenja za capability na datoj putanji.

    Pobeđuje **najduži opseg koji je prefiks putanje**; ako nijedan ne odgovara,
    važi red bez opsega; ako ni njega nema — `L0`. Time `L0` na `apps/policy/`
    obara opšti `L1`, a ne obrnuto.
    """
    redovi = list(TrustState.objects.filter(persona=persona, capability=capability)
                  .values_list("scope", "level"))
    if not redovi:
        return E.TrustLevel.L0
    p = normalize_path(path)
    najbolji, duzina = E.TrustLevel.L0, -1
    for scope, level in redovi:
        s = normalize_path(scope)
        if not s:
            if duzina < 0:
                najbolji = E.TrustLevel(level)
            continue
        if p == s.rstrip("/") or p.startswith(s if s.endswith("/") else s):
            if len(s) > duzina:
                najbolji, duzina = E.TrustLevel(level), len(s)
    return najbolji


def _grants(persona: Persona, now: datetime) -> frozenset[str]:
    return frozenset(CapabilityGrant.objects.filter(
        persona=persona, revoked_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)).values_list("capability", flat=True))


def build_context(persona: Persona, action_type: str, payload: dict, *, intent: str = "",
                  channel: ChannelAccount | None = None, now: datetime,
                  chash: str = "", approved: ApprovalRequest | None = None,
                  exclude_pk=None) -> engine.Context:
    hist = Action.objects.filter(persona=persona, action_type=action_type).exclude(
        status__in=[E.ActionStatus.PROPOSED.value, E.ActionStatus.POLICY_CHECK.value]
    ).exclude(pk=exclude_pk)
    return engine.Context(
        persona_id=persona.public_id, persona_status=E.PersonaStatus(persona.status),
        action_type=action_type, payload=payload, now=now, intent=intent,
        channel=_channel_ctx(channel), trust=trust_map(persona), grants=_grants(persona, now),
        kill_switches=active_kill_switches(),
        counts=_counts(persona, action_type, now, exclude_pk), history=hist.count(),
        history_on_channel=hist.filter(channel_account=channel).count() if channel else 0,
        rules=_rules(now), content_hash=chash,
        approved_hash=approved.payload_hash if approved else None,
        approved_class=E.ApprovalClass(approved.approval_class) if approved else None,
    )


def _fail_closed(ctx_now: datetime, reason: str) -> engine.Result:
    return engine.Result(
        effect=E.PolicyEffect.DENY, risk_score=100, risk_class=E.RiskClass.CRITICAL,
        risk_components={}, reason_codes=[E.PolicyReason.POLICY_ERROR.value, reason[:60]],
        matched_rules=[], approval_class=None, obligations=[], constraints={},
        expires_at=ctx_now, required_capabilities=[],
    )


def evaluate_safely(ctx: engine.Context) -> tuple[engine.Result, bool, int]:
    """Canon §12.4 — fail-closed: greška ili prekoračen rok je DENY, nikad dozvola."""
    t0 = time.monotonic()
    try:
        result = engine.evaluate(ctx)
        failed = False
    except Exception as exc:  # noqa: BLE001
        result, failed = _fail_closed(ctx.now, type(exc).__name__), True
    ms = int((time.monotonic() - t0) * 1000)
    if not failed and ms > settings.POLICY_EVAL_TIMEOUT_SECONDS * 1000:
        result, failed = _fail_closed(ctx.now, "TIMEOUT"), True
    return result, failed, ms


def decision_view(r: engine.Result, *, decision_id: str | None, input_hash: str | None) -> dict:
    """Canon §8.4 — kanonski oblik odgovora."""
    return {
        "decision_id": decision_id, "effect": r.effect.value, "risk_score": r.risk_score,
        "risk_class": r.risk_class.value, "zone": r.zone.value,
        "reason_codes": r.reason_codes,
        "matched_rules": [f"{m['key']}@v{m['version']}" for m in r.matched_rules],
        "obligations": [{"type": o} for o in r.obligations], "constraints": r.constraints,
        "policy_version": config.policy_version(),
        "input_hash": f"sha256:{input_hash}" if input_hash else None,
        "expires_at": r.expires_at.isoformat().replace("+00:00", "Z"),
        "approval_class": r.approval_class.value if r.approval_class else None,
        "risk_components": r.risk_components,
    }


# ---------------------------------------------------------------- predlog i odluka


@dataclass
class Proposal:
    action: Action
    decision: PolicyDecision
    approval: ApprovalRequest | None
    created: bool
    result: engine.Result | None = None


def propose(persona: Persona, action_type: str, payload: dict[str, Any], *,
            intent: str = "", target_ref: str = "", channel: ChannelAccount | None = None,
            run: AgentRun | None = None, plan_step: PlanStep | None = None,
            now: datetime | None = None) -> Proposal:
    """Planner (ili operator) predlaže; policy odlučuje. Canon §9.1."""
    now = now or timezone.now()
    chash = content_hash(payload)
    key = idempotency_key(persona.public_id, action_type, target_ref, chash,
                          str(plan_step.id) if plan_step else None)
    with transaction.atomic():
        # Brava na personu serijalizuje brojanje limita (Policy v0.1 §19: quota atomicity).
        Persona.objects.select_for_update().get(pk=persona.pk)
        existing = Action.objects.filter(idempotency_key=key).first()
        if existing:
            return Proposal(existing, existing.policy_decision
                            or existing.decisions.order_by("-evaluated_at").first(),
                            existing.approvals.order_by("-created_at").first(), False)
        caps = config.action_types().get(action_type, [])
        action = Action.objects.create(
            public_id=I.ulid_public_id(I.EntityKind.ACTION, now), persona=persona, run=run,
            plan_step=plan_step, channel_account=channel, action_type=action_type,
            capability=caps[0] if caps else "", status=E.ActionStatus.PROPOSED,
            target_ref=target_ref[:500], intent=intent or action_type, input_json=payload,
            content_hash=chash, idempotency_key=key,
            max_attempts=E.MAX_ATTEMPTS_BY_KIND[
                "read" if action_type in ("channel.read.public", "browser.page.read")
                else "write"],
            trace_id=_trace(),
        )
        bus.emit("action.proposed",
                 {"action_id": action.public_id, "action_type": action_type,
                  **({"plan_step_id": str(plan_step.id)} if plan_step else {})},
                 persona_id=persona.public_id, run_id=_run_id(action))
        decision, approval, result = _decide(action, now=now)
        return Proposal(action, decision, approval, True, result)


def _decide(action: Action, *, now: datetime, approved: ApprovalRequest | None = None
            ) -> tuple[PolicyDecision, ApprovalRequest | None, engine.Result]:
    persona = action.persona
    action.status = E.ActionStatus.POLICY_CHECK
    action.save(update_fields=["status", "updated_at"])
    ctx = build_context(persona, action.action_type, action.input_json, intent=action.intent,
                        channel=action.channel_account, now=now, chash=action.content_hash,
                        approved=approved, exclude_pk=action.pk)
    r, failed, ms = evaluate_safely(ctx)
    decisive = (PolicyRule.objects.filter(key=r.decisive_rule_key).order_by("-version").first()
                if r.decisive_rule_key else None)
    d = PolicyDecision.objects.create(
        public_id=I.ulid_public_id(I.EntityKind.POLICY_DECISION, now), action=action,
        persona=persona, effect=r.effect.value, risk_score=r.risk_score,
        risk_class=r.risk_class.value, risk_components=r.risk_components,
        matched_rules=r.matched_rules, decisive_rule=decisive, reason_code=r.reason_code,
        reason=", ".join(r.reason_codes), approval_class=r.approval_class.value
        if r.approval_class else None, fail_closed=failed, evaluator_version=EVALUATOR_VERSION,
        context_hash=_input_hash(action), evaluated_at=now, eval_duration_ms=ms,
        trace_id=_trace(), policy_version=config.policy_version(),
        reason_codes=r.reason_codes, obligations=r.obligations, constraints=r.constraints,
        expires_at=r.expires_at,
    )
    bus.emit("policy.decision.created",
             {"decision_id": d.public_id, "effect": d.effect, "risk_score": d.risk_score,
              "risk_class": d.risk_class, "reason_codes": r.reason_codes},
             persona_id=persona.public_id, run_id=_run_id(action))
    action.policy_decision = d
    action.risk_score, action.risk_class = r.risk_score, r.risk_class.value
    approval = None

    if r.effect == E.PolicyEffect.ALLOW:
        action.status = E.ActionStatus.QUEUED
        action.error_code = ""
        action.save(update_fields=["status", "policy_decision", "risk_score", "risk_class",
                                   "error_code", "updated_at"])
        bus.emit("action.queued",
                 {"action_id": action.public_id, "queue": _queue_for(action.action_type).value,
                  "priority": min(9, r.risk_score // 12)},
                 persona_id=persona.public_id, run_id=_run_id(action))
        # F6 (ADR-0008): ALLOW je jedini ulaz u red za izvršenje.
        from apps.runtime.executor import enqueue

        enqueue(action, now=now)
    elif r.effect == E.PolicyEffect.REQUIRE_APPROVAL:
        action.status = E.ActionStatus.APPROVAL_PENDING
        action.save(update_fields=["status", "policy_decision", "risk_score", "risk_class",
                                   "updated_at"])
        klass = r.approval_class or E.ApprovalClass.A3
        approval = ApprovalRequest.objects.create(
            public_id=I.ulid_public_id(I.EntityKind.APPROVAL_REQUEST, now), action=action,
            decision=d, approval_class=klass.value, status=E.ApprovalStatus.PENDING,
            payload_hash=action.content_hash, requested_by=current().actor_id,
            reason=", ".join(r.reason_codes),
            expires_at=now + timedelta(minutes=E.APPROVAL_TTL_MINUTES[klass]),
            expiry_effect=E.APPROVAL_EXPIRY_EFFECT[klass],
        )
        bus.emit("approval.requested",
                 {"approval_id": approval.public_id, "approval_class": klass.value,
                  "expires_at": approval.expires_at.isoformat().replace("+00:00", "Z"),
                  "payload_hash": approval.payload_hash},
                 persona_id=persona.public_id, run_id=_run_id(action))
    else:
        _block(action, "THROTTLED" if r.effect == E.PolicyEffect.THROTTLE else
               E.ExecutionOutcome.DENIED_BY_POLICY.value, r.reason_code)
        if r.hard_hits:
            _hard_prohibition(action, d, r)
    return d, approval, r


def _block(action: Action, outcome: str, reason_code: str | None) -> None:
    action.status = E.ActionStatus.BLOCKED
    action.error_code = (reason_code or outcome)[:80]
    action.completed_at = timezone.now()
    action.save(update_fields=["status", "policy_decision", "risk_score", "risk_class",
                               "error_code", "completed_at", "updated_at"])
    bus.emit("action.blocked",
             {"action_id": action.public_id, "outcome": outcome, "reason_code": reason_code},
             persona_id=action.persona.public_id, run_id=_run_id(action))


def _hard_prohibition(action: Action, d: PolicyDecision, r: engine.Result) -> None:
    """Canon §9.4–9.5: SEV1, capability na L0, persona SUSPENDED."""
    persona = action.persona
    open_incident(E.IncidentSeverity.SEV1, "hard_prohibition",
                  f"Tvrda zabrana: {', '.join(r.hard_hits)} ({action.action_type})",
                  persona=persona, action=action, decision=d, reason_code=r.hard_hits[0])
    caps = r.required_capabilities or list(
        TrustState.objects.filter(persona=persona).values_list("capability", flat=True))
    for cap in caps:
        _set_trust(persona, cap, E.TrustLevel.L0, actor="system:policy",
                   reason=f"HARD_PROHIBITION:{r.hard_hits[0]}", automatic=True)
    if persona.status != E.PersonaStatus.SUSPENDED.value:
        before = persona.status
        Persona.objects.filter(pk=persona.pk).update(status=E.PersonaStatus.SUSPENDED.value)
        persona.status = E.PersonaStatus.SUSPENDED.value
        audit.record("policy.persona.suspended", severity=E.AuditSeverity.CRITICAL,
                     persona=persona, action=action, before={"status": before},
                     after={"status": persona.status}, details={"prohibitions": r.hard_hits})


def reevaluate(action: Action, *, now: datetime | None = None) -> PolicyDecision:
    """Nova odluka za postojeću akciju (npr. posle promene pravila)."""
    now = now or timezone.now()
    with transaction.atomic():
        action = Action.objects.select_for_update().get(pk=action.pk)
        if action.status not in (E.ActionStatus.PROPOSED.value, E.ActionStatus.QUEUED.value,
                                 E.ActionStatus.POLICY_CHECK.value,
                                 E.ActionStatus.RETRY_WAIT.value):
            raise PolicyError("VERSION_CONFLICT",
                              f"Akcija u statusu {action.status} se ne evaluira ponovo.",
                              {"status": action.status})
        approved = action.approvals.filter(status__in=[
            E.ApprovalStatus.APPROVED.value, E.ApprovalStatus.APPROVED_WITH_CHANGES.value],
            payload_hash=action.content_hash).first()
        d, _, _ = _decide(action, now=now, approved=approved)
        return d


# ---------------------------------------------------------------- odobrenja


def decide_approval(approval: ApprovalRequest, decision: E.ApprovalStatus, *, actor: str,
                    role: E.Role | None, reason: str = "",
                    payload_override: dict | None = None,
                    now: datetime | None = None) -> ApprovalRequest:
    """Canon §8.3, §15.3 — odobrava se SADRŽAJ; izmena pravi novi hash."""
    now = now or timezone.now()
    allowed = {E.ApprovalStatus.APPROVED, E.ApprovalStatus.APPROVED_WITH_CHANGES,
               E.ApprovalStatus.REJECTED}
    if decision not in allowed:
        raise PolicyError("VALIDATION_ERROR", f"Odluka mora biti jedna od {sorted(allowed)}.")
    with transaction.atomic():
        ap = ApprovalRequest.objects.select_for_update(of=("self",)).select_related(
            "action", "action__persona").get(pk=approval.pk)
        action = Action.objects.select_for_update().get(pk=ap.action_id)
        if ap.status != E.ApprovalStatus.PENDING.value:
            raise PolicyError("VERSION_CONFLICT", f"Odobrenje je već {ap.status}.",
                              {"status": ap.status})
        if now >= ap.expires_at:
            raise PolicyError("VERSION_CONFLICT", "Odobrenje je isteklo.",
                              {"expires_at": ap.expires_at.isoformat()})
        if ap.payload_hash != action.content_hash:
            raise PolicyError("VERSION_CONFLICT",
                              "Sadržaj akcije se promenio posle zahteva za odobrenje.")
        before_hash = action.content_hash
        if decision == E.ApprovalStatus.APPROVED_WITH_CHANGES:
            if not payload_override:
                raise PolicyError("VALIDATION_ERROR",
                                  "APPROVED_WITH_CHANGES traži payload_override.")
            action.input_json = {**action.input_json, **payload_override}
            action.content_hash = content_hash(action.input_json)
            action.save(update_fields=["input_json", "content_hash", "updated_at"])
            ap.payload_hash = action.content_hash  # odobrenje prati NOVI sadržaj
        ap.status = decision.value
        ap.decided_by, ap.decided_role = actor, role.value if role else None
        ap.decision_note, ap.decided_at = reason, now
        ap.save()
        bus.emit("approval.resolved",
                 {"approval_id": ap.public_id, "decision": ap.status, "decided_by": actor},
                 persona_id=action.persona.public_id, run_id=_run_id(action))
        audit.record("policy.approval.decided", persona=action.persona, action=action,
                     before={"payload_hash": before_hash},
                     after={"payload_hash": action.content_hash, "status": ap.status},
                     details={"approval_id": ap.public_id, "reason": reason,
                              "changed": before_hash != action.content_hash})
        if decision == E.ApprovalStatus.REJECTED:
            action.status = E.ActionStatus.CANCELLED
            action.error_code = "APPROVAL_REJECTED"
            action.completed_at = now
            action.save(update_fields=["status", "error_code", "completed_at", "updated_at"])
        else:
            # Policy v0.1 §17.3 — posle odobrenja ponovna provera, pa tek onda red.
            _decide(action, now=now, approved=ap)
        # ADR-0021 — ako akcija stoji kao korak plana, odluka nastavlja plan
        # ili ga zaustavlja sa razlogom. Radi se posle transakcije, da kvar
        # motora plana ne poništi samu odluku.
        transaction.on_commit(lambda a=action, d=decision, r=reason: _resume_plan(a, d, r))
        return ap


def _resume_plan(action: Action, decision: E.ApprovalStatus, reason: str) -> None:
    from apps.orchestration import plans

    try:
        plans.on_action_decided(
            action, approved=decision != E.ApprovalStatus.REJECTED, reason=reason)
    except Exception as e:  # noqa: BLE001 — plan ne sme da obori odluku
        audit.record("plan.resume_failed", persona=action.persona, action=action,
                     severity=E.AuditSeverity.WARNING, details={"error": str(e)[:200]})


def expire_approvals(now: datetime | None = None) -> int:
    """Canon §15.2 — istekao TTL; efekat po klasi."""
    now = now or timezone.now()
    n = 0
    for ap in ApprovalRequest.objects.select_related("action", "action__persona").filter(
            status=E.ApprovalStatus.PENDING.value, expires_at__lte=now):
        with transaction.atomic():
            ap = ApprovalRequest.objects.select_for_update().get(pk=ap.pk)
            if ap.status != E.ApprovalStatus.PENDING.value:
                continue
            klass = E.ApprovalClass(ap.approval_class)
            ap.status = E.ApprovalStatus.EXPIRED.value
            ap.save(update_fields=["status", "updated_at"])
            action = ap.action
            action.status = _EXPIRY_STATUS[klass]
            action.error_code = f"APPROVAL_EXPIRED:{ap.expiry_effect}"
            action.completed_at = now
            action.save(update_fields=["status", "error_code", "completed_at", "updated_at"])
            bus.emit("approval.resolved",
                     {"approval_id": ap.public_id, "decision": ap.status,
                      "decided_by": "system:expiry"},
                     persona_id=action.persona.public_id, run_id=_run_id(action))
            if klass == E.ApprovalClass.A4:
                open_incident(E.IncidentSeverity.SEV2, "approval_expired",
                              f"A4 odobrenje isteklo bez odluke ({action.public_id})",
                              persona=action.persona, action=action, decision=ap.decision,
                              reason_code="APPROVAL_EXPIRED")
            n += 1
    return n


# ---------------------------------------------------------------- poverenje


def _set_trust(persona: Persona, capability: str, level: E.TrustLevel, *, actor: str,
               reason: str, evidence: str = "", automatic: bool = False,
               scope: str = "") -> bool:
    now = timezone.now()
    scope = normalize_path(scope) if scope else ""
    ts, _ = TrustState.objects.select_for_update().get_or_create(
        persona=persona, capability=capability, scope=scope,
        defaults={"level": E.TrustLevel.L0.value, "granted_at": now})
    before = E.TrustLevel(ts.level)
    changed = before != level
    ts.level = level.value
    ts.granted_at = now
    ts.evidence_ref = evidence[:512] or ts.evidence_ref
    ts.version += 1
    if automatic and config.trust_at_least(before, level) and changed:
        ts.auto_downgrade_count += 1
        ts.last_downgrade_at = now
    ts.save()

    cfg = config.capability(capability) or {}
    minimum = E.TrustLevel(cfg.get("min_trust_level", "L0"))
    active = CapabilityGrant.objects.filter(persona=persona, capability=capability,
                                            channel_account__isnull=True,
                                            revoked_at__isnull=True)
    # Dozvola (`CapabilityGrant`) je opšta i nema opseg. Red sa opsegom zato ne
    # dira dozvolu: on samo sužava ili proširuje nivo u svom delu koda, a pravo
    # da capability uopšte postoji ostaje na redu bez opsega (ADR-0034).
    if scope:
        pass
    elif config.trust_at_least(level, minimum) and minimum != E.TrustLevel.L0:
        if not active.exists():
            CapabilityGrant.objects.create(persona=persona, capability=capability,
                                           min_trust_level=minimum.value, granted_by=actor,
                                           granted_at=now, evidence_ref=evidence[:512])
    else:
        active.update(revoked_at=now, revoked_reason=reason[:500])
    if changed:
        bus.emit("trust.level.changed",
                 {"capability": capability, "from_level": before.value,
                  "to_level": level.value, "reason": reason[:200], "scope": scope},
                 persona_id=persona.public_id)
        audit.record("policy.trust.changed", persona=persona,
                     severity=E.AuditSeverity.WARNING if automatic else E.AuditSeverity.INFO,
                     before={"capability": capability, "level": before.value},
                     after={"capability": capability, "level": level.value},
                     details={"reason": reason, "evidence": evidence,
                              "automatic": automatic, "scope": scope})
    return changed


def change_trust(persona: Persona, capability: str, level: E.TrustLevel, *, actor: str,
                 reason: str, evidence: str = "", scope: str = "") -> bool:
    """Canon §3.11 — L3/L4 se ne dodeljuju; capability mora postojati u katalogu."""
    if level not in E.ASSIGNABLE_TRUST_LEVELS:
        raise PolicyError("VALIDATION_ERROR",
                          f"{level.value} je rezervisan (Canon §3.11) i ne može se dodeliti.")
    if config.capability(capability) is None:
        raise PolicyError("VALIDATION_ERROR", f"Nepoznat capability {capability!r}.",
                          {"allowed": sorted(config.capabilities()["capabilities"])})
    if not reason.strip():
        raise PolicyError("VALIDATION_ERROR", "Promena poverenja traži razlog.")
    if scope and (zona := path_is_protected(scope)):
        raise PolicyError("PROTECTED_PATH",
                          f"`{zona}` je zaštićena zona (ADR-0034): tu se poverenje ne "
                          "dodeljuje ni na jednom nivou.")
    with transaction.atomic():
        return _set_trust(persona, capability, level, actor=actor, reason=reason,
                          evidence=evidence, scope=scope)


# ---------------------------------------------------------------- kill-switch


def _in_scope(scope: E.KillSwitchScope, target: str, statuses=_OPEN):
    base = Action.objects.filter(status__in=[s.value for s in statuses])
    if scope == E.KillSwitchScope.GLOBAL:
        return base
    if scope == E.KillSwitchScope.PERSONA:
        return base.filter(persona__public_id=target)
    if scope == E.KillSwitchScope.CHANNEL:
        return base.filter(channel_account__channel_type=target)
    if scope == E.KillSwitchScope.ACCOUNT:
        return base.filter(channel_account_id=target)
    caps_types = [t for t, caps in config.action_types().items() if target in caps]
    return base.filter(Q(capability=target) | Q(action_type__in=caps_types))


def _in_flight(scope: E.KillSwitchScope, target: str):
    return _in_scope(scope, target, statuses=(E.ActionStatus.RUNNING,))


def activate_kill_switch(scope: E.KillSwitchScope, target: str, *, reason: str,
                         actor: str) -> KillSwitch:
    """Canon §9.6 — stop odmah. Otvorene akcije u opsegu prelaze u BLOCKED."""
    if scope == E.KillSwitchScope.GLOBAL:
        target = ""
    elif not target:
        raise PolicyError("VALIDATION_ERROR", f"{scope.value} traži target.")
    if not reason.strip():
        raise PolicyError("VALIDATION_ERROR", "Kill-switch traži razlog.")
    t0 = time.monotonic()
    now = timezone.now()
    with transaction.atomic():
        existing = KillSwitch.objects.filter(scope=scope.value, target_ref=target,
                                             is_active=True).first()
        if existing:
            return existing
        try:
            with transaction.atomic():
                ks = KillSwitch.objects.create(scope=scope.value, target_ref=target,
                                               is_active=True, reason=reason,
                                               activated_by=actor, activated_at=now)
        except IntegrityError:
            return KillSwitch.objects.get(scope=scope.value, target_ref=target, is_active=True)
        stopped = 0
        for action in _in_scope(scope, target).select_for_update(of=("self",)).select_related(
                "persona"):
            action.status = E.ActionStatus.BLOCKED
            action.error_code = "KILL_SWITCH"
            action.completed_at = now
            action.save(update_fields=["status", "error_code", "completed_at", "updated_at"])
            action.approvals.filter(status=E.ApprovalStatus.PENDING.value).update(
                status=E.ApprovalStatus.CANCELLED.value)
            bus.emit("action.blocked",
                     {"action_id": action.public_id,
                      "outcome": E.ExecutionOutcome.DENIED_BY_POLICY.value,
                      "reason_code": E.PolicyReason.KILL_SWITCH_ACTIVE.value},
                     persona_id=action.persona.public_id, run_id=_run_id(action))
            stopped += 1
        # F6: akcije u letu (RUNNING) staje sam worker na sledećoj proveri
        # (CancelToken) — tako se zna da li je spoljni efekat nastao.
        in_flight = _in_flight(scope, target).count()
        ks.stop_latency_ms = int((time.monotonic() - t0) * 1000)
        ks.save(update_fields=["stop_latency_ms"])
        bus.emit("killswitch.activated",
                 {"scope": scope.value, "target": target or None, "activated_by": actor},
                 persona_id=target if scope == E.KillSwitchScope.PERSONA else None)
        audit.record("policy.killswitch.activated", severity=E.AuditSeverity.CRITICAL,
                     after={"scope": scope.value, "target": target},
                     details={"reason": reason, "blocked_actions": stopped,
                              "in_flight": in_flight,
                              "stop_latency_ms": ks.stop_latency_ms})
    return ks


def release_kill_switch(ks: KillSwitch, *, actor: str, reason: str) -> KillSwitch:
    """Blokirane akcije OSTAJU blokirane — posle stopa ide novi predlog, ne nastavak."""
    if not reason.strip():
        raise PolicyError("VALIDATION_ERROR", "Puštanje kill-switch-a traži razlog.")
    with transaction.atomic():
        ks = KillSwitch.objects.select_for_update().get(pk=ks.pk)
        if not ks.is_active:
            raise PolicyError("VERSION_CONFLICT", "Kill-switch je već pušten.")
        ks.is_active = False
        ks.released_by, ks.released_at = actor, timezone.now()
        ks.save()
        bus.emit("killswitch.cleared",
                 {"scope": ks.scope, "target": ks.target_ref or None, "cleared_by": actor},
                 persona_id=ks.target_ref if ks.scope == E.KillSwitchScope.PERSONA.value
                 else None)
        audit.record("policy.killswitch.cleared", severity=E.AuditSeverity.WARNING,
                     after={"scope": ks.scope, "target": ks.target_ref},
                     details={"reason": reason})
    return ks


# ---------------------------------------------------------------- incidenti


def open_incident(severity: E.IncidentSeverity, kind: str, title: str, *, persona=None,
                  action=None, decision=None, reason_code: str,
                  now: datetime | None = None) -> PolicyIncident:
    now = now or timezone.now()
    for _ in range(5):
        seq = PolicyIncident.objects.filter(public_id__startswith=f"INC-{now:%Y%m%d}-").count() + 1
        try:
            with transaction.atomic():
                inc = PolicyIncident.objects.create(
                    public_id=I.incident_public_id(now.date(), seq), severity=severity.value,
                    incident_kind=kind, title=title[:220], persona=persona, action=action,
                    decision=decision, occurred_at=now, detected_at=now, trace_id=_trace(),
                    summary=reason_code,
                )
            break
        except IntegrityError:
            continue
    else:
        raise RuntimeError("nije moguće dodeliti broj incidenta")
    bus.emit("policy.incident.opened",
             {"incident_id": inc.public_id, "severity": inc.severity, "reason_code": reason_code},
             persona_id=persona.public_id if persona else None,
             run_id=_run_id(action) if action else None)
    return inc


def canonical(obj: Any) -> str:
    return canonical_json(obj)
