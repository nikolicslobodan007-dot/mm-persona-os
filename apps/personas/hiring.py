"""Zapošljavanje agenta — od praznog do spremnog, u jednom potezu. ADR-0023.

Prvi agent je nastao ručno pisanim seed-om (`seed_agent_001`). Drugi bi tako
značio kopiranje dvesta linija, a deseti hiljaditi ne bi ni bio moguć. Ovde je
isti posao sveden na jednu funkciju koja traži samo ono što je stvarno lično:
**ime i radno mesto**. Sve ostalo se izvodi iz organizacije ili ima polaznu
vrednost koja se kasnije menja.

Tri pravila:

  1. **Agent se rađa kao `DRAFT` i postaje `READY` kroz pravi prelaz statusa**
     (`lifecycle.change_status`) — sa razlogom i audit zapisom. Tako sandučić
     nastaje istim putem kao i kod prvog agenta (ADR-0016), bez prečice.
  2. **Radno mesto ne daje nijednu dozvolu** (ADR-0017). Novi agent kreće sa
     `L0` na svakom capability-ju; poverenje se dodeljuje odvojeno i namerno.
  3. **Ništa se ne izmišlja u tišini.** Osobine dobijaju polazne vrednosti sa
     odstupanjem koje zavisi od ID-a — isto pri svakom pokretanju — a dosije
     ostaje prazan dok ga čovek ne popuni.
"""

from __future__ import annotations

import random
import re
import unicodedata
from datetime import UTC, datetime, time
from decimal import Decimal

from django.db import transaction

from apps.behaviour.models import BehaviourState, RoutineTemplate, RoutineWindow
from apps.channels.models import ChannelAccount, ChannelCapability
from apps.personas import org
from apps.personas.lifecycle import change_status
from apps.personas.models import (
    Biography,
    IdentityFact,
    Persona,
    PersonaAlias,
    PersonaTag,
    PersonaTagLink,
    Position,
    TraitProfile,
    VoiceProfile,
)
from apps.social_graph.models import Actor
from common import enums as E
from common import ids as I

NOW = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

#: Polazne osobine (Canon §5). Odstupaju po agentu, ali oko iste sredine —
#: firma zapošljava odrasle, savesne ljude, ne slučajne brojeve.
BASE_TRAITS: dict[str, float] = {
    "openness": 0.72, "conscientiousness": 0.78, "extraversion": 0.55,
    "agreeableness": 0.68, "emotional_stability": 0.74, "curiosity": 0.76,
    "humor": 0.40, "formality": 0.60, "risk_tolerance": 0.35,
    "commercial_intensity": 0.40, "contrarian": 0.30, "evidence_preference": 0.82,
}
#: Koliko osobina sme da odstupi od sredine. Dovoljno da se dvoje ne poklope,
#: premalo da neko ispadne iz karaktera firme.
TRAIT_SPREAD = 0.12

BASE_STATE: dict[str, str] = {
    "energy": "0.700", "valence": "0.150", "arousal": "0.400",
    "cognitive_load": "0.200", "social_appetite": "0.500", "curiosity_now": "0.650",
    "focus": "0.650", "novelty_need": "0.450", "stress": "0.150",
    "content_pressure": "0.250", "inbox_pressure": "0.100",
    "topic_saturation": "0.100", "risk_alert": "0.000",
}

#: Radni dan i vikend — isti ritam kao kod prvog agenta, jer je i posao isti.
ROUTINES: dict[tuple[str, int], list[tuple[str, time, time, str]]] = {
    ("weekday", 0b0011111): [
        ("read", time(8, 0), time(9, 30), "0.850"),
        ("work", time(9, 30), time(12, 30), "0.900"),
        ("post", time(12, 30), time(13, 30), "0.550"),
        ("social", time(17, 0), time(18, 30), "0.600"),
        ("rest", time(21, 0), time(23, 0), "0.950"),
    ],
    ("weekend", 0b1100000): [
        ("read", time(10, 0), time(12, 0), "0.600"),
        ("social", time(18, 0), time(19, 30), "0.400"),
        ("rest", time(22, 0), time(23, 59), "0.980"),
    ],
}

#: Rečenice koje nijedan agent ne sme da izgovori (Canon §9.4).
BANNED = ["kao ljudsko biće", "ja sam osoba", "nisam AI", "revolucionarno",
          "game changer"]


class HiringError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def slugify_sr(name: str) -> str:
    """„Jovan Ilić" → `jovan-ilic`. Latinica bez kvačica, jer slug ide u URL."""
    plain = unicodedata.normalize("NFKD", name.replace("đ", "dj").replace("Đ", "Dj"))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def next_public_id() -> str:
    """Sledeći broj po redu (P-00001, P-00002, …). Rupe se ne popunjavaju —
    broj agenta je trajan i ne nasleđuje se."""
    used = [int(p[2:]) for p in Persona.objects.values_list("public_id", flat=True)
            if p[2:].isdigit()]
    return I.persona_public_id(max(used, default=0) + 1)


def _traits_for(public_id: str) -> dict[str, Decimal]:
    rnd = random.Random(public_id)          # noqa: S311 — nije kriptografija
    out = {}
    for key, base in BASE_TRAITS.items():
        value = min(0.95, max(0.05, base + rnd.uniform(-TRAIT_SPREAD, TRAIT_SPREAD)))
        out[key] = Decimal(f"{value:.3f}")
    return out


@transaction.atomic
def hire(*, name: str, position: Position, actor: str, niches: list[str] | None = None,
         locale: str = "sr-Latn", timezone_name: str = "Europe/Belgrade") -> Persona:
    """Pravi agenta, postavlja ga na radno mesto i vodi ga do `READY`."""
    name = (name or "").strip()
    if len(name.split()) < 2:
        raise HiringError("VALIDATION_ERROR", "Agent ima ime i prezime.")
    label = f"{name} (AI)"          # Canon §17 — oznaka je u imenu, ne u fusnoti
    slug = slugify_sr(name)
    if Persona.objects.filter(slug=slug).exists():
        raise HiringError("VALIDATION_ERROR", f"Slug „{slug}” je već zauzet.")
    public_id = next_public_id()

    persona = Persona.objects.create(
        public_id=public_id, slug=slug, display_name=label,
        persona_type=E.PersonaType.AI_CREATOR.value,
        status=E.PersonaStatus.DRAFT.value,
        runtime_environment=E.RuntimeEnvironment.SIMULATION.value,
        trust_level=E.TrustLevel.L0.value,
        disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE.value,
        disclosure_required=True, primary_locale=locale, timezone=timezone_name,
        birth_date_model=None, metadata={"canon": "1.1", "hired_by": actor})
    PersonaAlias.objects.create(persona=persona, alias_type="public_label",
                                value=label, is_primary=True)
    IdentityFact.objects.create(
        persona=persona, namespace="identity", key="is_ai_persona", valid_from=NOW,
        value_json={"value": True}, provenance=E.Provenance.USER_PROVIDED.value,
        confidence=Decimal("1.000"), is_public=True, priority=100)

    _biography(persona, position)
    TraitProfile.objects.create(persona=persona, **_traits_for(public_id))
    _voice(persona)
    BehaviourState.objects.create(
        persona=persona, **{k: Decimal(v) for k, v in BASE_STATE.items()},
        free_minutes=240, attention_remaining=Decimal("8.00"), next_wake_at=NOW,
        wake_priority=E.WAKE_PRIORITY_VALUE[E.WakePriority.ROUTINE_WINDOW],
        state_version=1)
    _routines(persona)
    _interests(persona, niches or [])
    Actor.objects.create(persona=persona, kind=E.ActorKind.PERSONA.value,
                         display_name=label, canonical_key=f"persona:{public_id}",
                         is_internal=True)
    _sandbox(persona, slug)
    org.assign(persona, position, actor=actor)

    change_status(persona, E.PersonaStatus.READY, actor=actor,
                  roles={E.Role.PERSONA_MANAGER},
                  reason=f"Zaposlen na radno mesto {position.code}.")
    persona.refresh_from_db()
    return persona


# ---------------------------------------------------------------- delovi


def _biography(persona: Persona, position: Position) -> None:
    dep = position.department
    zadaci = "; ".join(str(d) for d in (position.duties or [])[:3])
    Biography.objects.create(
        persona=persona,
        headline=f"{position.title}"
                 + (f" — {position.specialty}" if position.specialty else ""),
        short_bio=(f"AI agent u sektoru „{dep.name}”. Nije čovek i to nikada ne "
                   f"krije."),
        long_bio=(f"{persona.display_name} radi u sektoru „{dep.name}”, na mestu "
                  f"„{position.title}”."
                  + (f" Posao: {zadaci}." if zadaci else "")
                  + " Svaka tvrdnja koju iznese ima proverljiv izvor; kada izvora "
                    "nema, tvrdnje nema. Ne predstavlja se kao stvarna osoba."),
        occupation_title=position.title,
        industry=dep.name,
        location_label="Srbija",
        values_json=["dokaz pre tvrdnje", "kratko", "bez preterivanja"])


def _voice(persona: Persona) -> None:
    VoiceProfile.objects.create(
        persona=persona, tone="smireno, konkretno, bez marketinškog rečnika",
        register="neutral", verbosity=Decimal("0.400"),
        sentence_length_bias=Decimal("0.350"), emoji_allowed=False, hashtag_max=0,
        reading_level=10, signature_phrases=[], banned_phrases=list(BANNED),
        languages=[persona.primary_locale, "en"])


def _routines(persona: Persona) -> None:
    for (name, mask), windows in ROUTINES.items():
        template = RoutineTemplate.objects.create(
            persona=persona, name=name, day_mask=mask, priority=0, is_enabled=True)
        for activity, start, end, probability in windows:
            RoutineWindow.objects.create(
                template=template, activity_type=activity, start_local=start,
                end_local=end, probability=Decimal(probability),
                min_minutes=15, max_minutes=90)


def _interests(persona: Persona, niches: list[str]) -> None:
    for raw in niches:
        slug = slugify_sr(raw)
        if not slug:
            continue
        tag, _ = PersonaTag.objects.get_or_create(
            slug=slug, defaults={"name": raw.strip(), "category": "niche"})
        PersonaTagLink.objects.get_or_create(
            persona=persona, tag=tag,
            defaults={"weight": Decimal("0.800"), "source": "manual"})


def _sandbox(persona: Persona, slug: str) -> None:
    """Samo sandbox nalog. Nijedan stvarni profil se ne pravi (Canon §16.2)."""
    account = ChannelAccount.objects.create(
        persona=persona, channel_type=E.ChannelType.SANDBOX.value,
        handle=f"{slug}-sandbox",
        identity_vehicle=E.IdentityVehicle.SANDBOX.value,
        status=E.AccountStatus.ACTIVE.value,
        disclosure_label_status=E.DisclosureLabelStatus.NOT_REQUIRED.value,
        credential_ref="")
    for capability in ("social.read_public", "web.read_public"):
        ChannelCapability.objects.create(
            account=account, capability=capability, is_enabled=True, source="policy",
            evidence_level=E.EvidenceLevel.RESPONSE_ONLY.value,
            limits_json={"per_day": E.PILOT_DAILY_LIMITS["web_reads"]})
