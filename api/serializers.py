"""Ulaz i izlaz API-ja. Canon §2 (dualni ID), §3 (enum-i), §9.4, §17.

Izlaz se gradi funkcijama, ne ModelSerializer-om: oblik odgovora je ugovor
(Canon §8), pa treba da bude vidljiv u kodu polje po polje, a ne izveden
iz modela tako da ga svaka migracija tiho menja.

Interni UUID nikada ne izlazi napolje — samo `public_id` (Canon §2.1).
Decimalne vrednosti idu kao stringovi da se ne izgubi preciznost (0.860
ostaje 0.860, ne 0.86000000000000001).
"""

from __future__ import annotations

import re
from typing import Any

from django.utils.text import slugify
from rest_framework import serializers

from common import enums as E
from common import ids as I

# ---------------------------------------------------------------- pomoćno


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def _dec(value) -> str | None:
    return None if value is None else str(value)


def etag_for(version: int) -> str:
    return f'"v{version}"'


def parse_if_match(raw: str | None) -> int | None:
    """Prihvata `"v3"`, `W/"v3"`, `v3` i `3`. Vraća verziju ili None."""
    if not raw:
        return None
    m = re.fullmatch(r'\s*(?:W/)?"?v?(\d+)"?\s*', raw)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- persona


def persona_out(p) -> dict[str, Any]:
    return {
        "public_id": p.public_id,
        "slug": p.slug,
        "display_name": p.display_name,
        "persona_type": p.persona_type,
        "status": p.status,
        "runtime_environment": p.runtime_environment,
        "trust_level": p.trust_level,
        "disclosure_mode": p.disclosure_mode,
        "disclosure_required": p.disclosure_required,
        "primary_locale": p.primary_locale,
        "timezone": p.timezone,
        "version": p.version,
        "activated_at": _iso(p.activated_at),
        "archived_at": _iso(p.archived_at),
        "created_at": _iso(p.created_at),
        "updated_at": _iso(p.updated_at),
        "metadata": p.metadata,
    }


#: Canon §17 — obavezna oznaka u imenu za tipove kod kojih je oznaka obavezna.
AI_MARKER = "(AI)"


class PersonaCreateIn(serializers.Serializer):
    """POST /api/v1/personas. Persona uvek nastaje kao DRAFT u SIMULATION, L0.

    Status, okruženje i trust se ovde ne zadaju: aktivacija, prelaz iz
    simulacije i promena poverenja su zasebne radnje sa svojim odobrenjima
    (Canon §3.2, §9.5, §15.2 A3), a ne polja koja se popune pri kreiranju.
    """

    public_id = serializers.CharField(required=False, max_length=16)
    slug = serializers.SlugField(required=False, max_length=120)
    display_name = serializers.CharField(max_length=160)
    persona_type = serializers.ChoiceField(choices=E.PersonaType.values())
    disclosure_mode = serializers.ChoiceField(choices=E.DisclosureMode.values())
    disclosure_required = serializers.BooleanField(required=False, default=True)
    primary_locale = serializers.CharField(max_length=16)
    timezone = serializers.CharField(max_length=64)
    metadata = serializers.DictField(required=False, default=dict)

    def validate_public_id(self, value: str) -> str:
        try:
            return I.validate_public_id(I.EntityKind.PERSONA, value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_timezone(self, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise serializers.ValidationError("Nije IANA vremenska zona.") from exc
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        ptype = E.PersonaType(attrs["persona_type"])
        if ptype in E.DISCLOSURE_ALWAYS_REQUIRED:
            # Canon §3.4 — za ove tipove oznaka nije izbor.
            if attrs.get("disclosure_required") is False:
                raise serializers.ValidationError(
                    {"disclosure_required": f"Za {ptype.value} oznaka je uvek obavezna (§3.4)."}
                )
            attrs["disclosure_required"] = True
            # Canon §17, §9.4 t.2 — AI priroda se vidi već u imenu.
            if AI_MARKER not in attrs["display_name"]:
                raise serializers.ValidationError(
                    {"display_name": f"Ime mora sadržati oznaku {AI_MARKER} (Canon §17)."}
                )
        return attrs


class PersonaPatchIn(serializers.Serializer):
    """PATCH /api/v1/personas/{public_id}. Samo polja bez sopstvenog toka odobrenja."""

    display_name = serializers.CharField(max_length=160, required=False)
    disclosure_mode = serializers.ChoiceField(choices=E.DisclosureMode.values(), required=False)
    primary_locale = serializers.CharField(max_length=16, required=False)
    timezone = serializers.CharField(max_length=64, required=False)
    metadata = serializers.DictField(required=False)

    validate_timezone = PersonaCreateIn.validate_timezone

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {k: "Ovo polje se ne menja kroz PATCH." for k in sorted(unknown)}
            )
        if not attrs:
            raise serializers.ValidationError("Nijedno polje za izmenu.")
        persona = self.context["persona"]
        name = attrs.get("display_name", persona.display_name)
        if (
            E.PersonaType(persona.persona_type) in E.DISCLOSURE_ALWAYS_REQUIRED
            and AI_MARKER not in name
        ):
            raise serializers.ValidationError(
                {"display_name": f"Ime mora sadržati oznaku {AI_MARKER} (Canon §17)."}
            )
        return attrs


def unique_slug(base: str) -> str:
    from apps.personas.models import Persona

    root = slugify(base)[:100] or "persona"
    slug, n = root, 2
    while Persona.objects.filter(slug=slug).exists():
        slug, n = f"{root}-{n}", n + 1
    return slug


# ---------------------------------------------------------------- snapshot


_TRAIT_FIELDS = (
    "openness", "conscientiousness", "extraversion", "agreeableness", "emotional_stability",
    "curiosity", "humor", "formality", "risk_tolerance", "commercial_intensity",
    "contrarian", "evidence_preference",
)
_STATE_FIELDS = (
    "energy", "valence", "arousal", "cognitive_load", "social_appetite", "curiosity_now",
    "focus", "novelty_need", "stress", "content_pressure", "inbox_pressure",
    "topic_saturation", "risk_alert", "attention_remaining",
)

#: Memorije koje nikada ne ulaze u snapshot za planner.
_HIDDEN_MEMORY = (E.MemoryStatus.DELETED, E.MemoryStatus.SUPERSEDED, E.MemoryStatus.ARCHIVED)


def _related(obj, name):
    try:
        return getattr(obj, name)
    except Exception:  # noqa: BLE001 — RelatedObjectDoesNotExist
        return None


def snapshot_out(p, *, memory_limit: int = 10) -> dict[str, Any]:
    """Konsolidovan pogled za planner (ugovor API v0.1 §9).

    Svaki pod-model nosi svoju verziju, da planner zna da li je radio nad
    zastarelim stanjem kad predloži akciju.
    """
    bio = _related(p, "biography")
    traits = _related(p, "trait_profile")
    voice = _related(p, "voice_profile")
    state = _related(p, "behaviour_state")

    memories = (
        p.memories.exclude(status__in=[s.value for s in _HIDDEN_MEMORY])
        .order_by("-salience", "-created_at")[:memory_limit]
    )
    accounts = p.channel_accounts.prefetch_related("capabilities").order_by("channel_type")

    return {
        "persona": persona_out(p),
        "versions": {
            "persona": p.version,
            "biography": getattr(bio, "story_version", None),
            "traits": getattr(traits, "trait_version", None),
            "voice": getattr(voice, "voice_version", None),
            "state": getattr(state, "state_version", None),
        },
        "biography": None if bio is None else {
            "headline": bio.headline,
            "short_bio": bio.short_bio,
            "occupation_title": bio.occupation_title,
            "industry": bio.industry,
            "values": bio.values_json,
        },
        "traits": None if traits is None else {f: _dec(getattr(traits, f)) for f in _TRAIT_FIELDS},
        "voice": None if voice is None else {
            "tone": voice.tone,
            "register": voice.register,
            "verbosity": _dec(voice.verbosity),
            "emoji_allowed": voice.emoji_allowed,
            "hashtag_max": voice.hashtag_max,
            "banned_phrases": voice.banned_phrases,
            "languages": voice.languages,
        },
        "state": None if state is None else (
            {f: _dec(getattr(state, f)) for f in _STATE_FIELDS}
            | {
                "free_minutes": state.free_minutes,
                "next_wake_at": _iso(state.next_wake_at),
                "wake_priority": state.wake_priority,
            }
        ),
        "channels": [
            {
                "channel_type": a.channel_type,
                "identity_vehicle": a.identity_vehicle,
                "handle": a.handle,
                "status": a.status,
                "disclosure_label_status": a.disclosure_label_status,
                "capabilities": sorted(c.capability for c in a.capabilities.all() if c.is_enabled),
            }
            for a in accounts
        ],
        "memories": [
            {
                "memory_type": m.memory_type,
                "status": m.status,
                "provenance": m.provenance,
                "title": m.title,
                "content": m.content,
                "salience": _dec(m.salience),
                "confidence": _dec(m.confidence),
            }
            for m in memories
        ],
    }


# ---------------------------------------------------------------- orkestracija


def run_out(r) -> dict[str, Any]:
    return {
        "run_id": r.public_id,
        "persona_id": r.persona.public_id,
        "status": r.status,
        "wake_priority": r.wake_priority,
        "started_at": _iso(r.started_at),
        "ended_at": _iso(r.ended_at),
        "trace_id": r.trace_id.hex if r.trace_id else None,
        "cost_eur_cents": r.cost_eur_cents,
        "decision": r.decision,
        "reason_code": r.reason_code or None,
        "summary": r.summary_json or {},
        "plans": [{"plan_id": pl.public_id, "status": pl.status, "goal": pl.goal}
                  for pl in r.plans.order_by("created_at")],
        "actions": [action_summary(a) for a in r.actions.order_by("created_at")],
    }


def action_summary(a) -> dict[str, Any]:
    return {
        "action_id": a.public_id,
        "action_type": a.action_type,
        "status": a.status,
        "risk_score": a.risk_score,
        "risk_class": a.risk_class,
    }


def action_out(a) -> dict[str, Any]:
    decision = a.policy_decision
    return action_summary(a) | {
        "persona_id": a.persona.public_id,
        "run_id": a.run.public_id if a.run_id else None,
        "capability": a.capability,
        "intent": a.intent,
        "target_ref": a.target_ref,
        "policy_decision_id": decision.public_id if decision else None,
        "scheduled_for": _iso(a.scheduled_for),
        "deadline_at": _iso(a.deadline_at),
        "started_at": _iso(a.started_at),
        "completed_at": _iso(a.completed_at),
        "error_code": a.error_code,
        "trace_id": a.trace_id.hex if a.trace_id else None,
        "attempts": [attempt_out(t) for t in a.attempts.order_by("attempt_number")],
    }


def attempt_out(t) -> dict[str, Any]:
    return {
        "attempt_number": t.attempt_number,
        "outcome": t.outcome,
        "reason_code": t.reason_code,
        "evidence_level": t.evidence_level,
        "started_at": _iso(t.started_at),
        "finished_at": _iso(t.finished_at),
    }


def decision_out(d) -> dict[str, Any]:
    """Canon §8.4. `zone` je izvedena — tu je radi čitljivosti, ne kao izvor."""
    return {
        "decision_id": d.public_id,
        "effect": d.effect,
        "risk_score": d.risk_score,
        "risk_class": d.risk_class,
        "zone": d.zone.value,
        "reason_code": d.reason_code,
        "reason": d.reason,
        "matched_rules": d.matched_rules,
        "approval_class": d.approval_class,
        "fail_closed": d.fail_closed,
        "evaluated_at": _iso(d.evaluated_at),
    }


def approval_out(ap) -> dict[str, Any]:
    return {
        "approval_id": ap.public_id,
        "approval_class": ap.approval_class,
        "status": ap.status,
        "expires_at": _iso(ap.expires_at),
        "decided_by": ap.decided_by or None,
        "decided_at": _iso(ap.decided_at),
    }


# ---------------------------------------------------------------- audit


def audit_out(ev) -> dict[str, Any]:
    return {
        "id": ev.id,
        "occurred_at": _iso(ev.occurred_at),
        "severity": ev.severity,
        "event_key": ev.event_key,
        "persona_id": ev.persona.public_id if ev.persona_id else None,
        "actor_ref": ev.actor_ref,
        "trace_id": ev.trace_id.hex if ev.trace_id else None,
        "payload": ev.payload,
        "payload_hash": ev.payload_hash,
    }



def run_brief(r) -> dict[str, Any]:
    """Red u vremenskoj liniji persone — bez planova i akcija."""
    summary = r.summary_json or {}
    return {
        "run_id": r.public_id,
        "started_at": _iso(r.started_at),
        "wake_priority": r.wake_priority,
        "decision": r.decision,
        "reason_code": r.reason_code or None,
        "activity": summary.get("activity"),
        "window": (summary.get("window") or {}).get("template"),
        "next_wake_at": summary.get("next_wake_at"),
    }
