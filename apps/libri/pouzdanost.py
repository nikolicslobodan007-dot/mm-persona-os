"""Pouzdanost tvrdnje po pet osa (ADR-0031 sloj 4b, §3.3).

Uz postojeći jedan broj po vrsti izvora (`KnowledgeSource.trust_score`), svaka
tvrdnja (`KnowledgeFact`, predikat `libri.tvrdnja`) dobija pet osa:

  pouzdanost     — koliko je izvor pouzdan (iz `trust_score`),
  blizina        — iz prve ruke vs posredno (iz `source_kind`),
  potkrepljenost — koliko DRUGIH izvora tvrdi isto,
  nezavisnost    — koliko RAZLIČITIH saglasnih izvora (uz „isti original = jedan"),
  stabilnost     — pada ako postoji protivrečan izvor (isti subjekat+predikat,
                   druga vrednost).

Ovo NIJE vađenje iz teksta nego **deterministička računica** nad metapodacima
izvora i grafom tvrdnji (Canon §21 — osnova sada, LLM/bogatiji signali kasnije).
Ne bira se pobednik među protivrečnim izvorima (ADR-0006 §3): stabilnost samo
pada, tvrdnje ostaju obe. Izolovano u `apps/libri`; upis delete+recreate po izvoru.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

OSE = ("pouzdanost", "nezavisnost", "blizina", "potkrepljenost", "stabilnost")

# Blizina događaju po vrsti izvora (iz prve ruke → posredno). Dokumentovana skala;
# trust_score ostaje zaseban broj (Canon trust bande su za trust_score, ne za ovo).
_BLIZINA = {
    "system_observation": 0.95,
    "first_party_user_input": 0.90,
    "synthetic_world_event": 0.80,
    "public_web_source": 0.50,
    "llm_inference": 0.30,
}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _kljuc(tv) -> tuple[str, str]:
    return (str(tv.subject).strip().lower(), str(tv.predicate).strip().lower())


def _vrednost(tv) -> str:
    return str(tv.vrednost).strip().lower()


def oceni(tv, kontekst) -> dict:
    """Pet osa (0..1) + `ukupno` za tvrdnju `tv` u kontekstu svih tvrdnji.

    `tv` i članovi `kontekst` nose: subject, predicate, vrednost, trust,
    source_kind, source_id. Čista funkcija — bez baze.
    """
    kljuc = _kljuc(tv)
    isti = [g for g in kontekst if _kljuc(g) == kljuc]
    saglasni = {g.source_id for g in isti if _vrednost(g) == _vrednost(tv)}
    protivrecni = {g.source_id for g in isti if _vrednost(g) != _vrednost(tv)}
    drugi_saglasni = saglasni - {tv.source_id}

    pouzdanost = _clamp(float(tv.trust))
    blizina = _BLIZINA.get(tv.source_kind, 0.50)
    potkrepljenost = _clamp(0.2 + 0.4 * len(drugi_saglasni))
    n = len(saglasni)
    nezavisnost = 0.5 if n <= 1 else _clamp(0.5 + 0.25 * (n - 1))
    if protivrecni:
        udeo = len(protivrecni) / max(1, n + len(protivrecni))
        stabilnost = _clamp(1.0 - 0.5 * udeo)
    else:
        stabilnost = 1.0
    ukupno = round(
        (pouzdanost + nezavisnost + blizina + potkrepljenost + stabilnost) / 5, 3)
    return {
        "pouzdanost": round(pouzdanost, 3), "nezavisnost": round(nezavisnost, 3),
        "blizina": round(blizina, 3), "potkrepljenost": round(potkrepljenost, 3),
        "stabilnost": round(stabilnost, 3), "ukupno": ukupno,
        "detalji": {"saglasnih_izvora": n, "drugih_saglasnih": len(drugi_saglasni),
                    "protivrecnih_izvora": len(protivrecni)},
    }


def _tv(fact) -> SimpleNamespace:
    oj = fact.object_json or {}
    return SimpleNamespace(
        subject=fact.subject, predicate=fact.predicate,
        vrednost=str(oj.get("vrednost", "")),
        trust=float(fact.source.trust_score or 0),
        source_kind=fact.source.source_kind, source_id=fact.source_id,
    )


def upisi(document) -> dict[str, int]:
    """Oceni sve tvrdnje dokumentovog izvora u kontekstu CELE baze tvrdnji.

    Kontekst je ceo korpus `libri.tvrdnja` (da potkrepljenost/nezavisnost/stabilnost
    vide druge izvore). Delete+recreate po izvoru. Zove se unutar `bind(actor)`.
    """
    from decimal import Decimal

    from django.db import transaction

    from apps.libri.models import OcenaTvrdnje
    from apps.libri.tvrdnje import PREDIKAT
    from apps.memory.models import KnowledgeFact

    izvor = document.source
    if izvor is None:
        raise ValueError(
            f"Dokument {document.document_id} nema izvor (KnowledgeSource) — "
            "ocena ne sme da postoji bez tvrdnje i izvora (Canon §4.1)."
        )
    svi = list(KnowledgeFact.objects.filter(predicate=PREDIKAT).select_related("source"))
    kontekst = [_tv(f) for f in svi]
    ciljni = [f for f in svi if f.source_id == izvor.id]

    def _d(v: float) -> Decimal:
        return Decimal(str(v))

    with transaction.atomic():
        stare = OcenaTvrdnje.objects.filter(fact__source=izvor)
        obrisano = stare.count()
        stare.delete()
        kreirane = []
        for f in ciljni:
            o = oceni(_tv(f), kontekst)
            kreirane.append(OcenaTvrdnje(
                fact=f, pouzdanost=_d(o["pouzdanost"]), nezavisnost=_d(o["nezavisnost"]),
                blizina=_d(o["blizina"]), potkrepljenost=_d(o["potkrepljenost"]),
                stabilnost=_d(o["stabilnost"]), ukupno=_d(o["ukupno"]),
                object_json=o["detalji"],
            ))
        OcenaTvrdnje.objects.bulk_create(kreirane)
    return {"ocenjeno": len(kreirane), "obrisano": obrisano}


def scenario_namespaces(tvrdnje: list[dict[str, Any]]) -> list[SimpleNamespace]:
    """Pomoć za merenje: pretvori scenario-rečnike u namespace-ove za `oceni`."""
    return [SimpleNamespace(**t) for t in tvrdnje]
