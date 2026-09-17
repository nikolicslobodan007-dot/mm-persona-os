"""Kanonski identifikatori — MM Persona OS Canon v1.1, §2.

Dualni ID: `id` je UUIDv4 i nikada se ne prikazuje; `public_id` je čitljiv i
koristi se u UI-ju, logovima, dokumentaciji i razgovoru.

ULID je izabran umesto UUID-a u čitljivom ID-ju jer je leksikografski
sortabilan po vremenu — bitno u audit pregledu i DLQ analizi.

Bez Django zavisnosti: uvozi se iz testova i iz workera jednako.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

__all__ = [
    "EntityKind",
    "SPECS",
    "new_uuid",
    "new_ulid",
    "persona_public_id",
    "ulid_public_id",
    "media_asset_public_id",
    "incident_public_id",
    "parse_persona_number",
    "validate_public_id",
    "kind_of",
]

# Crockford base32, bez I, L, O i U — sprečava zamenu sa 1 i 0.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: Canon §2.2 — Persona je jedini entitet sa brojčanim ID-jem.
PERSONA_DIGITS = 5
MAX_PERSONA_NUMBER = 10**PERSONA_DIGITS - 1


@dataclass(frozen=True)
class IdSpec:
    """Opis jednog oblika `public_id` iz Canon §2.2."""

    prefix: str
    pattern: re.Pattern[str]
    description: str


class EntityKind:
    """Entiteti koji imaju `public_id` (Canon §2.2).

    Svi ostali modeli imaju samo UUID; `public_id` im se dodaje tek kada
    se pojave u UI-ju ili u razgovoru sa operatorom, i to kroz ADR.
    """

    PERSONA = "Persona"
    AGENT_RUN = "AgentRun"
    AGENT_PLAN = "AgentPlan"
    ACTION = "Action"
    WORLD_EVENT = "WorldEvent"
    POLICY_DECISION = "PolicyDecision"
    APPROVAL_REQUEST = "ApprovalRequest"
    MEDIA_ASSET = "MediaAsset"
    POLICY_INCIDENT = "PolicyIncident"


_ULID_RE = "[0-9A-HJKMNP-TV-Z]{26}"

#: Canon §2.2 — devet entiteta, devet oblika.
SPECS: dict[str, IdSpec] = {
    EntityKind.PERSONA: IdSpec(
        "P-", re.compile(r"^P-\d{5}$"), "P- + 5 cifara sa vodećim nulama"
    ),
    EntityKind.AGENT_RUN: IdSpec(
        "RUN-", re.compile(rf"^RUN-{_ULID_RE}$"), "RUN- + ULID"
    ),
    EntityKind.AGENT_PLAN: IdSpec(
        "PLN-", re.compile(rf"^PLN-{_ULID_RE}$"), "PLN- + ULID"
    ),
    EntityKind.ACTION: IdSpec(
        "ACT-", re.compile(rf"^ACT-{_ULID_RE}$"), "ACT- + ULID"
    ),
    EntityKind.WORLD_EVENT: IdSpec(
        "EVT-", re.compile(rf"^EVT-{_ULID_RE}$"), "EVT- + ULID"
    ),
    EntityKind.POLICY_DECISION: IdSpec(
        "POL-", re.compile(rf"^POL-{_ULID_RE}$"), "POL- + ULID"
    ),
    EntityKind.APPROVAL_REQUEST: IdSpec(
        "APR-", re.compile(rf"^APR-{_ULID_RE}$"), "APR- + ULID"
    ),
    EntityKind.MEDIA_ASSET: IdSpec(
        "IMG-", re.compile(r"^IMG-P\d{5}-\d{4}$"), "IMG- + P00001 + - + 4 cifre"
    ),
    EntityKind.POLICY_INCIDENT: IdSpec(
        "INC-", re.compile(r"^INC-\d{8}-\d{3}$"), "INC- + YYYYMMDD + 3 cifre"
    ),
}

#: ULID-ovani entiteti — svi osim Persona, MediaAsset i PolicyIncident.
_ULID_KINDS: frozenset[str] = frozenset(
    {
        EntityKind.AGENT_RUN,
        EntityKind.AGENT_PLAN,
        EntityKind.ACTION,
        EntityKind.WORLD_EVENT,
        EntityKind.POLICY_DECISION,
        EntityKind.APPROVAL_REQUEST,
    }
)


def new_uuid() -> uuid.UUID:
    """Interni primarni ključ. Canon §2.1."""
    return uuid.uuid4()


def new_ulid(when: datetime | None = None) -> str:
    """26-znakovni ULID: 48 bita vremena + 80 bita slučajnosti.

    Leksikografsko sortiranje odgovara hronološkom, što je ceo razlog izbora.
    """
    if when is None:
        ms = time.time_ns() // 1_000_000
    else:
        if when.tzinfo is None:
            raise ValueError("when mora biti timezone-aware (UTC)")
        ms = int(when.astimezone(timezone.utc).timestamp() * 1000)
    if not 0 <= ms < (1 << 48):
        raise ValueError(f"vreme van ULID opsega: {ms}")

    randomness = int.from_bytes(os.urandom(10), "big")  # 80 bita
    value = (ms << 80) | randomness

    out = [""] * 26
    for i in range(25, -1, -1):
        out[i] = _CROCKFORD[value & 0x1F]
        value >>= 5
    return "".join(out)


def persona_public_id(number: int) -> str:
    """`P-00001`. Canon §2.2.

    Kratki oblici (tri ili četiri cifre) su zabranjeni; Faza 13 ih
    koristi i to je errata Canon §19.
    """
    if not isinstance(number, int) or isinstance(number, bool):
        raise TypeError(f"number mora biti int, dobijeno {type(number).__name__}")
    if not 1 <= number <= MAX_PERSONA_NUMBER:
        raise ValueError(f"broj persone van opsega 1-{MAX_PERSONA_NUMBER}: {number}")
    return f"P-{number:0{PERSONA_DIGITS}d}"


def ulid_public_id(kind: str, when: datetime | None = None) -> str:
    """`RUN-01K5XQ…`, `ACT-01K5XQ…` itd. Canon §2.2."""
    if kind not in _ULID_KINDS:
        raise ValueError(
            f"{kind} nema ULID oblik; poznati: {sorted(_ULID_KINDS)}"
        )
    return f"{SPECS[kind].prefix}{new_ulid(when)}"


def media_asset_public_id(persona_public: str, sequence: int) -> str:
    """`IMG-P00001-0047`. Canon §2.2."""
    if not SPECS[EntityKind.PERSONA].pattern.match(persona_public):
        raise ValueError(f"nevažeći persona public_id: {persona_public!r}")
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise TypeError("sequence mora biti int")
    if not 0 <= sequence <= 9999:
        raise ValueError(f"redni broj van opsega 0-9999: {sequence}")
    return f"IMG-{persona_public.replace('-', '')}-{sequence:04d}"


def incident_public_id(when: date, sequence: int) -> str:
    """`INC-20260915-001`. Canon §2.2."""
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise TypeError("sequence mora biti int")
    if not 1 <= sequence <= 999:
        raise ValueError(f"redni broj van opsega 1-999: {sequence}")
    return f"INC-{when:%Y%m%d}-{sequence:03d}"


def parse_persona_number(public_id: str) -> int:
    """`P-00037` → 37. Canon §2.2."""
    if not SPECS[EntityKind.PERSONA].pattern.match(public_id):
        raise ValueError(f"nevažeći persona public_id: {public_id!r}")
    return int(public_id[2:])


def validate_public_id(kind: str, public_id: str) -> str:
    """Vraća `public_id` ako odgovara obliku za `kind`, inače podiže ValueError."""
    try:
        spec = SPECS[kind]
    except KeyError:
        raise ValueError(f"nepoznat entitet: {kind!r}") from None
    if not spec.pattern.match(public_id):
        raise ValueError(
            f"{public_id!r} ne odgovara obliku za {kind} ({spec.description})"
        )
    return public_id


def kind_of(public_id: str) -> str:
    """Prepoznaje entitet po obliku ID-ja. Canon §2.2."""
    for kind, spec in SPECS.items():
        if spec.pattern.match(public_id):
            return kind
    raise ValueError(f"{public_id!r} ne odgovara nijednom kanonskom obliku")
