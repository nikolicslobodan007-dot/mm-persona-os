"""Šta radno mesto traži i šta agentu nedostaje. ADR-0037.

Ovaj modul ne donosi nijednu odluku o dozvoli — samo poredi. Odluku i dalje
donosi motor pravila isključivo po `TrustState` (ADR-0017: radno mesto nije
dozvola). Ovde se odgovara na pitanje koje se ranije nije moglo postaviti:
**šta ovom agentu nedostaje da bi radio posao za koji je zaposlen.**
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.personas.models import Assignment, Persona, Position
from apps.policy import config as policy_config
from apps.policy import service as policy
from common import enums as E

__all__ = ["Trazeno", "needs_of", "gap_for", "positions_of", "personas_on"]


@dataclass(frozen=True)
class Trazeno:
    """Jedna stavka onoga što posao traži."""

    capability: str
    level: E.TrustLevel
    scope: str = ""

    def __str__(self) -> str:
        gde = f" @ {self.scope}" if self.scope else ""
        return f"{self.capability}{gde} → {self.level.value}"


def _parse(stavka) -> Trazeno | None:
    """Prima `{"capability": …, "level": …, "scope": …}` ili `"cap@L1"`/`"cap@L1:opseg"`.

    Neispravna stavka se preskače tiho samo ovde: `needs` je opis posla i sme da
    bude nepotpun, dok se dodela (koja menja stanje) uvek proverava.
    """
    if isinstance(stavka, dict):
        cap = str(stavka.get("capability") or "").strip()
        nivo = str(stavka.get("level") or "").strip().upper()
        opseg = policy.normalize_path(str(stavka.get("scope") or ""))
    elif isinstance(stavka, str) and "@" in stavka:
        cap, _, ostatak = stavka.partition("@")
        nivo, _, opseg = ostatak.partition(":")
        cap, nivo, opseg = cap.strip(), nivo.strip().upper(), policy.normalize_path(opseg)
    else:
        return None
    if not cap or nivo not in E.TrustLevel.values():
        return None
    return Trazeno(cap, E.TrustLevel(nivo), opseg)


def needs_of(position: Position) -> list[Trazeno]:
    out: list[Trazeno] = []
    for stavka in position.needs or []:
        t = _parse(stavka)
        if t is not None:
            out.append(t)
    return out


def positions_of(persona: Persona) -> list[Position]:
    """Radna mesta na kojima agent trenutno sedi (ADR-0017)."""
    return [
        a.position for a in Assignment.objects
        .filter(persona=persona, ended_at__isnull=True)
        .select_related("position")
    ]


def personas_on(position: Position) -> list[Persona]:
    return [
        a.persona for a in Assignment.objects
        .filter(position=position, ended_at__isnull=True)
        .select_related("persona")
    ]


def gap_for(persona: Persona, position: Position | None = None) -> list[Trazeno]:
    """Šta agentu nedostaje do onoga što njegov posao traži.

    Vraća stavke čiji je traženi nivo VIŠI od onoga što agent stvarno ima na toj
    putanji. Zaštićena zona se ne prijavljuje kao manjak — ona se ne otvara ni
    radnim mestom (ADR-0034 §5.1).
    """
    mesta = [position] if position is not None else positions_of(persona)
    manjak: dict[tuple[str, str], Trazeno] = {}
    for mesto in mesta:
        if mesto is None:
            continue
        for t in needs_of(mesto):
            if t.scope and policy.path_is_protected(t.scope):
                continue
            ima = policy.trust_for(persona, t.capability, t.scope)
            if policy_config.trust_at_least(ima, t.level):
                continue
            kljuc = (t.capability, t.scope)
            ranije = manjak.get(kljuc)
            if ranije is None or policy_config.trust_at_least(t.level, ranije.level):
                manjak[kljuc] = t
    return [manjak[k] for k in sorted(manjak)]
