"""Tvrdnje iz Libri blokova (ADR-0031 sloj 4a).

Blok → (subjekat, relacija, vrednost) → `KnowledgeFact`. Ekstraktor je
**zamenljiv sloj**: deterministička osnova sad (definicione rečenice „X je Y"),
a LLM se kasnije ukopča kroz isti potpis `izvuci(blocks) -> list[dict]` (Canon
§21 obrazac — prvo osnova + merenje, pa pravi alat).

Provenance je `OBSERVED`: tvrdnja je doslovno navedena u prvostranom izvoru, mi
je čitamo iz teksta — nije naša INFERENCA (Canon §10.4). `KnowledgeFact` nosi
poreklo do bloka (`object_json.block_id`), pa „nema činjenice bez izvora" važi
do nivoa bloka. Upis ide delete+recreate po izvoru (obrazac `vestine`/`recnik`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from apps.libri.pismo import VELIKA, u_latinicu

PREDIKAT = "libri.tvrdnja"

_KOPULA = (
    r"(je|su|jeste|jesu|predstavlja|predstavljaju|"
    r"označava|označavaju|podrazumeva|podrazumevaju|"
    r"је|су|јесте|јесу|представља|представљају|"
    r"означава|означавају|подразумева|подразумевају)"
)
_RECENICA = re.compile(r"[^.!?]+[.!?]")
_DEF = re.compile(
    rf"^\s*([{VELIKA}][\wčćžšđ]*(?:\s+[\wčćžšđ]+){{0,2}})\s+"
    + _KOPULA
    + r"\s+(.+?)\s*[.!?]?\s*$"
)
# Prečesto lažni subjekti (zamenice/pokaznice) — izbacujemo radi preciznosti.
_STOP = {"to", "ovo", "ono", "on", "ona", "one", "oni", "ovde", "tu", "tada"}


def _recenice(text: str) -> list[str]:
    return [m.group(0).strip() for m in _RECENICA.finditer(text or "")]


def izvuci(blocks: Iterable[Any]) -> list[dict]:
    """Vrati kandidat-tvrdnje iz blokova (čista funkcija, bez baze).

    Osnova hvata samo definicione rečenice sa kopulom (visoka preciznost, niži
    odziv — to je donja granica pre LLM-a). Svaka tvrdnja nosi `block_id` i
    `source_page` radi porekla.
    """
    out = []
    for b in blocks:
        if getattr(b, "block_type", "") != "paragraph":
            continue
        for rec in _recenice(b.text):
            m = _DEF.match(rec)
            if not m:
                continue
            subjekat = m.group(1).strip()
            relacija = m.group(2).strip()
            vrednost = m.group(3).strip()
            if u_latinicu(subjekat).lower() in _STOP or len(subjekat) < 3:
                continue
            if not (8 <= len(vrednost) <= 240):
                continue
            out.append({
                "subject": subjekat[:220],
                "relacija": relacija,
                "vrednost": vrednost,
                "block_id": b.block_id,
                "source_page": b.source_page,
                "confidence": 0.6,
            })
    return out


def upisi(document, *, kandidati: list[dict] | None = None) -> dict[str, int]:
    """Izvuci tvrdnje iz blokova dokumenta i upiši kao `KnowledgeFact`.

    Tvrdnje se vezuju za dokumentov `KnowledgeSource` (predicate=`libri.tvrdnja`).
    Delete+recreate za taj izvor (isti obrazac kao `vestine`/`recnik`): spajanje
    red po red ništa ne dobija, a ostavilo bi staro pored novog. Jedna transakcija.
    Zove se unutar `bind(actor)` (komanda to obezbeđuje).
    """
    from django.db import transaction

    from apps.memory.models import KnowledgeFact
    from common import enums as E

    izvor = document.source
    if izvor is None:
        raise ValueError(
            f"Dokument {document.document_id} nema izvor (KnowledgeSource) — "
            "tvrdnja ne sme da postoji bez izvora (Canon §4.1)."
        )
    if kandidati is None:
        kandidati = izvuci(document.blocks.all())
    with transaction.atomic():
        stare = KnowledgeFact.objects.filter(source=izvor, predicate=PREDIKAT)
        obrisano = stare.count()
        stare.delete()
        napravljene = KnowledgeFact.objects.bulk_create([
            KnowledgeFact(
                source=izvor, persona=None, subject=k["subject"],
                predicate=PREDIKAT, provenance=E.Provenance.OBSERVED.value,
                confidence=k["confidence"],
                object_json={
                    "relacija": k["relacija"], "vrednost": k["vrednost"],
                    "block_id": k["block_id"], "source_page": k["source_page"],
                },
            )
            for k in kandidati
        ])
    return {"upisano": len(napravljene), "obrisano": obrisano}
