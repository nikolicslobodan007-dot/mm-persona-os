"""Uvoz veština u bazu znanja — prva vrata (ADR-0074).

ADR-0074 kaže: materijal za ovu vrstu znanja daje čovek, agent ništa spolja
ne radi. Zato `uvezi()` ne pretpostavlja ni `uri` ni `license_box` — ona
dolaze kao argumenti, jer ih je čovek doneo uz materijal, i ne izmišljaju se
ovde.

Jedna veština je jedan `KnowledgeFact`: `subject` je ime veštine,
`predicate` je `vestina.postupak`, `object_json` nosi korake i napomene —
naš opis postupka, nikad doslovan prepis izvora (ADR-0074 tačka 3): takvo
polje se namerno ne upisuje.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from api import audit
from apps.memory.models import KnowledgeFact, KnowledgeSource
from common import enums as E

PREDIKAT = "vestina.postupak"


@dataclass(frozen=True)
class Vestina:
    """Jedna veština koju čovek unosi — opis postupka, ne tuđi tekst."""

    ime: str
    koraci: list[str]
    napomene: str
    pouzdanost: float


def uvezi(
    *,
    naslov_izvora: str,
    uri: str,
    license_box: E.LicenseBox,
    vestine: list[Vestina],
    actor: str,
) -> dict[str, int]:
    """Upisuje veštine u `KnowledgeSource`/`KnowledgeFact`. Vraća prebrojano.

    Ponovni uvoz **briše i upisuje ponovo** postojeće `KnowledgeFact` za taj
    izvor sa predikatom `vestina.postupak` — isti obrazac kao u Rečniku
    (apps/content/recnik.py), iz istog razloga: spajanje red po red ne bi
    ništa dobilo, a ostavilo bi staro da živi pored novog. Sve u jednoj
    transakciji.
    """
    for v in vestine:
        if not 0.0 <= v.pouzdanost <= 1.0:
            raise ValueError(f"Pouzdanost van [0,1] za veštinu '{v.ime}'.")

    with transaction.atomic():
        izvor, _ = KnowledgeSource.objects.get_or_create(
            persona=None, title=naslov_izvora,
            defaults={"source_kind": E.SourceKind.FIRST_PARTY_USER_INPUT.value,
                      "trust_score": 1.0, "uri": uri,
                      "license_box": E.LicenseBox(license_box).value,
                      "is_active": True})
        obrisano = KnowledgeFact.objects.filter(source=izvor, predicate=PREDIKAT).delete()[0]
        KnowledgeFact.objects.bulk_create([
            KnowledgeFact(
                source=izvor, persona=None, subject=v.ime[:220],
                predicate=PREDIKAT, provenance=E.Provenance.USER_PROVIDED.value,
                confidence=v.pouzdanost,
                object_json={"koraci": list(v.koraci), "napomene": v.napomene})
            for v in vestine
        ], batch_size=1000)
    broj = {"upisano": len(vestine), "obrisano": obrisano}
    audit.record("memory.vestina.loaded",
                 details={"izvor": naslov_izvora, "actor": actor, **broj})
    return broj
