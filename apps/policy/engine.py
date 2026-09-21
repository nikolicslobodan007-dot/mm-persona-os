"""Policy evaluator — čista funkcija. Canon §3.5–3.7, §6.4, §9; Policy v0.1 §3–§11.

    result = evaluate(ctx)

Bez baze, bez sata, bez slučajnosti: sve što treba stoji u `Context`-u, pa
se svaka odluka može ponoviti i objasniti. Redosled je fiksan i prvo „ne"
odlučuje; ali se svi razlozi skupljaju, da operator vidi celu sliku.

  1. Kill-switch                       → DENY  (uvek pobeđuje)
  2. Nepoznat ActionType               → DENY  (default deny)
  3. Tvrde zabrane (§9.4)              → DENY  + SEV1 + L0 + SUSPENDED
  4. Persona nije operativna           → DENY
  5. Capability: trust, grant, kanal,
     AI oznaka, parametri čitanja     → DENY
  6. Dnevni limiti (§9.3)              → THROTTLE (ukupno 40 se proverava prvo)
  7. Rizik (§9.2)                      → CRITICAL=DENY, HIGH=odobrenje,
                                          MEDIUM uz trust < L2 = odobrenje
  8. Pravila iz baze i capability-ji   → DENY / REQUIRE_APPROVAL / ALLOW
  9. Važeće odobrenje istog hash-a     → REQUIRE_APPROVAL je ispunjen

Prednost efekata: DENY > THROTTLE > REQUIRE_APPROVAL > ALLOW (§9.1 Policy v0.1).
Zona (GREEN/YELLOW/RED) se ne računa ovde — izvodi se iz efekta (Canon §3.7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from apps.policy import config, guards
from common import enums as E

_PRECEDENCE = {E.PolicyEffect.DENY: 3, E.PolicyEffect.THROTTLE: 2,
               E.PolicyEffect.REQUIRE_APPROVAL: 1, E.PolicyEffect.ALLOW: 0}
#: Od dve klase odobrenja bira se strožija (duža provera, oštriji ishod isteka).
_CLASS_STRICTNESS = {E.ApprovalClass.A4: 4, E.ApprovalClass.A3: 3,
                     E.ApprovalClass.A1: 2, E.ApprovalClass.A2: 1}
_OPERATIONAL = frozenset({E.PersonaStatus.READY, E.PersonaStatus.ACTIVE})
_LABEL_OK = frozenset({E.DisclosureLabelStatus.SET, E.DisclosureLabelStatus.NOT_REQUIRED})
_REGULATED = re.compile(
    r"\b(zdravlj|lek|lecen|dijagnoz|kredit|investic|akcij[ae] na berzi|kripto|"
    r"pravn|zakon|advokat|porez)\w*")
_FIGURES = re.compile(r"\d+[.,]?\d*\s*(%|eur|€|\$|din|miliona|hiljada)|\b\d{2,}\b")


@dataclass
class Channel:
    id: str
    channel_type: str
    status: str
    disclosure_label_status: str
    enabled_capabilities: frozenset[str]


@dataclass
class Rule:
    key: str
    version: int
    effect: E.PolicyEffect
    scope: str
    action_type: str = ""
    capability: str = ""
    channel_type: str = ""
    approval_class: E.ApprovalClass | None = None
    per_day: int | None = None
    prohibition_id: str | None = None
    is_hard: bool = False


@dataclass
class Context:
    persona_id: str
    persona_status: E.PersonaStatus
    action_type: str
    payload: dict[str, Any]
    now: datetime
    intent: str = ""
    channel: Channel | None = None
    trust: dict[str, E.TrustLevel] = field(default_factory=dict)
    grants: frozenset[str] = frozenset()
    kill_switches: list[tuple[str, str]] = field(default_factory=list)  # (scope, target)
    counts: dict[str, int] = field(default_factory=dict)  # "total", dimenzija, action_type
    history: int = 0  # koliko puta je ova persona već radila ovaj ActionType
    history_on_channel: int = 0
    rules: list[Rule] = field(default_factory=list)
    content_hash: str = ""
    approved_hash: str | None = None
    approved_class: E.ApprovalClass | None = None


@dataclass
class Result:
    effect: E.PolicyEffect
    risk_score: int
    risk_class: E.RiskClass
    risk_components: dict[str, int]
    reason_codes: list[str]
    matched_rules: list[dict[str, Any]]
    approval_class: E.ApprovalClass | None
    obligations: list[str]
    constraints: dict[str, Any]
    expires_at: datetime
    required_capabilities: list[str]
    hard_hits: list[str] = field(default_factory=list)
    decisive_rule_key: str | None = None

    @property
    def reason_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else E.PolicyReason.WITHIN_POLICY.value

    @property
    def zone(self) -> E.Zone:
        return E.EFFECT_TO_ZONE[self.effect]


# ---------------------------------------------------------------- rizik


def _audience(action_type: str, payload: dict) -> str:
    if payload.get("audience") in ("internal", "own_followers", "public", "named_individual"):
        return payload["audience"]
    if action_type in E.INTERNAL_ACTION_TYPES or action_type.endswith(".read") or \
            action_type in ("channel.read.public", "browser.page.read"):
        return "internal"
    if action_type == "channel.post.create":
        return "public"
    if action_type.startswith("mail."):
        return "named_individual"
    return "own_followers"


def _novelty(ctx: Context) -> str:
    if ctx.channel is not None and ctx.history_on_channel == 0 and \
            ctx.action_type not in E.INTERNAL_ACTION_TYPES:
        return "first_on_channel"
    if ctx.history > 20:
        return "routine"
    if ctx.history >= 5:
        return "familiar"
    return "new"


def _volume(used: int, cap: int) -> str:
    share = used / cap if cap else 1.0
    if share >= 1:
        return "at_cap"
    if share >= 0.8:
        return "under_100_pct"
    if share >= 0.5:
        return "under_80_pct"
    return "under_50_pct"


def _content(action_type: str, payload: dict, text: str) -> str:
    if payload.get("content_class") in config.weights()["content_risk"]:
        return payload["content_class"]
    if action_type in E.INTERNAL_ACTION_TYPES or action_type in ("channel.read.public",
                                                                   "browser.page.read"):
        return "neutral"
    if _REGULATED.search(text):
        return "regulated_topic"
    if "@" in text or payload.get("mentions"):
        return "names_third_party"
    if _FIGURES.search(text):
        return "claim_with_figures"
    return "neutral"


def _identity(ctx: Context, needs_label: bool) -> str:
    if not needs_label or ctx.channel is None:
        return "disclosure_not_required"
    status = E.DisclosureLabelStatus(ctx.channel.disclosure_label_status)
    return {E.DisclosureLabelStatus.SET: "disclosure_set",
            E.DisclosureLabelStatus.NOT_REQUIRED: "disclosure_not_required",
            E.DisclosureLabelStatus.SET_UNVERIFIED: "disclosure_unverified"}.get(
        status, "disclosure_missing")


def risk(ctx: Context, caps: list[str], needs_label: bool,
         min_trust: E.TrustLevel) -> dict[str, int]:
    w = config.weights()
    text = guards._text(ctx.payload, ctx.intent)
    internal = ctx.action_type in E.INTERNAL_ACTION_TYPES
    components = {
        "action_base_risk": int(w["action_base_risk"].get(ctx.action_type, 50)),
        "audience_risk": int(w["audience_risk"][_audience(ctx.action_type, ctx.payload)]),
        "novelty_risk": 0 if internal else int(w["novelty_risk"][_novelty(ctx)]),
        "volume_risk": 0 if internal else int(w["volume_risk"][_volume(
            ctx.counts.get("total", 0), config.rate_limits()["total_actions"])]),
        "content_risk": int(w["content_risk"][_content(ctx.action_type, ctx.payload, text)]),
        "platform_risk": int(w["platform_risk"].get(ctx.channel.channel_type, 0)
                             if ctx.channel else 0),
        "identity_risk": int(w["identity_risk"][_identity(ctx, needs_label)]),
        "trust_credit": int(w["trust_credit"][min_trust.value]) if caps else 0,
    }
    return components


def _score(c: dict[str, int]) -> int:
    total = sum(v for k, v in c.items() if k != "trust_credit") - c["trust_credit"]
    return max(0, min(100, total))


# ---------------------------------------------------------------- evaluacija


def _scope_hits(ctx: Context, caps: list[str]) -> bool:
    for scope, target in ctx.kill_switches:
        s = E.KillSwitchScope(scope)
        if s == E.KillSwitchScope.GLOBAL:
            return True
        if s == E.KillSwitchScope.PERSONA and target == ctx.persona_id:
            return True
        if s == E.KillSwitchScope.CAPABILITY and target in caps:
            return True
        if ctx.channel and s == E.KillSwitchScope.CHANNEL and target == ctx.channel.channel_type:
            return True
        if ctx.channel and s == E.KillSwitchScope.ACCOUNT and target == ctx.channel.id:
            return True
    return False


def _read_constraints_ok(payload: dict, required: dict) -> bool:
    got = payload.get("execution_constraints") or {}
    return (got.get("robots_respected") is True
            and got.get("user_agent_declared") == required["user_agent_declared"]
            and isinstance(got.get("rate_per_host_qps"), int | float)
            and 0 < got["rate_per_host_qps"] <= required["rate_per_host_qps"]
            and got.get("conditional_get") is True)


def _rule_applies(r: Rule, ctx: Context, caps: list[str]) -> bool:
    if r.is_hard:
        return False  # tvrde zabrane idu kroz guards, ne kroz poklapanje polja
    if r.action_type and r.action_type != ctx.action_type:
        return False
    if r.capability and r.capability not in caps:
        return False
    if r.channel_type and (ctx.channel is None or ctx.channel.channel_type != r.channel_type):
        return False
    return True


def evaluate(ctx: Context) -> Result:
    known = config.action_types()
    caps = list(known.get(ctx.action_type, []))
    cap_cfg = {c: config.capability(c) or {} for c in caps}
    needs_label = any(cfg.get("requires_disclosure_label") for cfg in cap_cfg.values())
    levels = [ctx.trust.get(c, E.TrustLevel.L0) for c in caps]
    min_trust = min(levels, key=lambda lv: list(E.TrustLevel).index(lv)) if levels \
        else E.TrustLevel.L0

    candidates: list[tuple[E.PolicyEffect, str, E.ApprovalClass | None, str | None]] = []
    matched: list[dict[str, Any]] = []
    hard_hits: list[str] = []
    obligations: list[str] = []
    constraints: dict[str, Any] = {}

    def deny(reason: E.PolicyReason, rule_key: str | None = None) -> None:
        candidates.append((E.PolicyEffect.DENY, reason.value, None, rule_key))

    # 1–2
    if _scope_hits(ctx, caps):
        deny(E.PolicyReason.KILL_SWITCH_ACTIVE)
    if ctx.action_type not in known:
        deny(E.PolicyReason.UNKNOWN_ACTION_TYPE)

    # 3 — tvrde zabrane
    hard_hits = guards.prohibitions(ctx.action_type, ctx.payload, ctx.intent)
    for pid in hard_hits:
        rule = next((r for r in ctx.rules if r.is_hard and r.prohibition_id == pid), None)
        if rule:
            matched.append({"key": rule.key, "version": rule.version, "effect": rule.effect.value})
        deny(E.PolicyReason.HARD_PROHIBITION, rule.key if rule else None)

    # 4
    if ctx.persona_status not in _OPERATIONAL:
        deny(E.PolicyReason.PERSONA_NOT_OPERATIONAL)

    # 5 — capability, kanal, oznaka
    external = ctx.action_type not in E.INTERNAL_ACTION_TYPES
    if ctx.action_type.startswith(("channel.", "mail.")) and ctx.channel is None:
        deny(E.PolicyReason.CHANNEL_REQUIRED)
    if ctx.channel is not None and ctx.channel.status != E.AccountStatus.ACTIVE.value:
        deny(E.PolicyReason.CHANNEL_NOT_ACTIVE)
    for cap in caps:
        cfg = cap_cfg[cap]
        minimum = E.TrustLevel(cfg.get("min_trust_level", "L0"))
        if not config.trust_at_least(ctx.trust.get(cap, E.TrustLevel.L0), minimum):
            deny(E.PolicyReason.TRUST_TOO_LOW)
        if minimum != E.TrustLevel.L0 and cap not in ctx.grants:
            deny(E.PolicyReason.CAPABILITY_NOT_GRANTED)
        if ctx.channel is not None and cap not in ctx.channel.enabled_capabilities:
            deny(E.PolicyReason.CHANNEL_CAPABILITY_DISABLED)
        if cfg.get("requires_disclosure_label"):
            obligations.append(E.Obligation.ENSURE_AI_DISCLOSURE.value)
            if ctx.channel is not None and \
                    E.DisclosureLabelStatus(ctx.channel.disclosure_label_status) not in _LABEL_OK:
                deny(E.PolicyReason.DISCLOSURE_MISSING)
        required = cfg.get("required_constraints")
        if required:
            obligations.append(E.Obligation.RESPECT_ROBOTS.value)
            constraints.update(required)
            if not _read_constraints_ok(ctx.payload, required):
                deny(E.PolicyReason.READ_CONSTRAINTS_MISSING)
        if cfg.get("requires_approval_class"):
            candidates.append((E.PolicyEffect.REQUIRE_APPROVAL,
                               E.PolicyReason.CAPABILITY_REQUIRES_APPROVAL.value,
                               E.ApprovalClass(cfg["requires_approval_class"]), None))

    # 6 — dnevni limiti (Canon §9.3): ukupni plafon prvi
    limits = config.rate_limits()
    if external:
        obligations.append(E.Obligation.CHECK_RATE_LIMIT.value)
        if ctx.counts.get("total", 0) >= limits["total_actions"]:
            candidates.append((E.PolicyEffect.THROTTLE, E.PolicyReason.DAILY_CAP_REACHED.value,
                               None, None))
        dims = [E.ACTION_RATE_DIMENSION.get(ctx.action_type)]
        if ctx.channel and ctx.channel.channel_type == E.ChannelType.X.value and \
                ctx.action_type == "channel.post.create":
            dims.append("x_posts")
        for dim in filter(None, dims):
            if ctx.counts.get(dim, 0) >= limits[dim]:
                candidates.append((E.PolicyEffect.THROTTLE,
                                   E.PolicyReason.DIMENSION_CAP_REACHED.value, None, None))
        obligations.append(E.Obligation.LOG_PAYLOAD_HASH.value)
    if ctx.action_type == "mail.send":
        obligations.append(E.Obligation.CHECK_SUPPRESSION_LIST.value)

    # 7 — rizik
    components = risk(ctx, caps, needs_label, min_trust)
    score = _score(components)
    klass = E.risk_class_for(score)
    fallback_class = next((E.ApprovalClass(c["requires_approval_class"])
                           for c in cap_cfg.values() if c.get("requires_approval_class")),
                          E.ApprovalClass.A2 if ctx.action_type == "channel.post.create"
                          else E.ApprovalClass.A1 if ctx.action_type.startswith("mail.")
                          else E.ApprovalClass.A3)
    if klass == E.RiskClass.CRITICAL:
        deny(E.PolicyReason.RISK_CRITICAL)
    elif klass == E.RiskClass.HIGH:
        candidates.append((E.PolicyEffect.REQUIRE_APPROVAL, E.PolicyReason.RISK_HIGH.value,
                           fallback_class, None))
    elif klass == E.RiskClass.MEDIUM and external and \
            not config.trust_at_least(min_trust, E.TrustLevel.L2):
        candidates.append((E.PolicyEffect.REQUIRE_APPROVAL,
                           E.PolicyReason.RISK_MEDIUM_LOW_TRUST.value, fallback_class, None))

    # 8 — pravila iz baze
    for r in ctx.rules:
        if not _rule_applies(r, ctx, caps):
            continue
        matched.append({"key": r.key, "version": r.version, "effect": r.effect.value})
        count = ctx.counts.get(f"type:{ctx.action_type}", 0) if r.action_type else \
            ctx.counts.get("total", 0)
        if r.per_day is not None and external and count >= r.per_day:
            candidates.append((E.PolicyEffect.THROTTLE,
                               E.PolicyReason.DIMENSION_CAP_REACHED.value, None, r.key))
        if r.effect == E.PolicyEffect.DENY:
            deny(E.PolicyReason.RULE_DENY, r.key)
        elif r.effect == E.PolicyEffect.REQUIRE_APPROVAL:
            candidates.append((E.PolicyEffect.REQUIRE_APPROVAL,
                               E.PolicyReason.RULE_REQUIRES_APPROVAL.value,
                               r.approval_class, r.key))

    # 9 — važeće odobrenje za TAČNO ovaj sadržaj ispunjava zahtev za odobrenjem
    approved = bool(ctx.approved_hash) and ctx.approved_hash == ctx.content_hash
    if approved:
        candidates = [c for c in candidates if c[0] != E.PolicyEffect.REQUIRE_APPROVAL]

    if candidates:
        top = max(_PRECEDENCE[c[0]] for c in candidates)
        winners = [c for c in candidates if _PRECEDENCE[c[0]] == top]
        effect = winners[0][0]
        reasons = [c[1] for c in winners] + [c[1] for c in candidates if c not in winners]
        classes = [c[2] for c in winners if c[2]]
        approval_class = (max(classes, key=lambda k: _CLASS_STRICTNESS[k])
                          if effect == E.PolicyEffect.REQUIRE_APPROVAL else None)
        decisive = next((c[3] for c in winners if c[3]), None)
    else:
        effect = E.PolicyEffect.ALLOW
        reasons = [E.PolicyReason.APPROVED.value if approved else
                   E.PolicyReason.WITHIN_POLICY.value]
        approval_class, decisive = None, None
    if approved and effect == E.PolicyEffect.ALLOW and reasons[0] != E.PolicyReason.APPROVED.value:
        reasons.insert(0, E.PolicyReason.APPROVED.value)

    ttl = (timedelta(minutes=E.APPROVAL_TTL_MINUTES[approval_class]) if approval_class
           else timedelta(minutes=E.POLICY_DECISION_TTL_MINUTES))
    kind = "read" if ctx.action_type in ("channel.read.public", "browser.page.read") else "write"
    constraints.setdefault("max_attempts", E.MAX_ATTEMPTS_BY_KIND[kind])
    return Result(
        effect=effect, risk_score=score, risk_class=klass, risk_components=components,
        reason_codes=list(dict.fromkeys(reasons)), matched_rules=matched,
        approval_class=approval_class, obligations=list(dict.fromkeys(obligations)),
        constraints=constraints, expires_at=ctx.now + ttl, required_capabilities=caps,
        hard_hits=hard_hits, decisive_rule_key=decisive,
    )
