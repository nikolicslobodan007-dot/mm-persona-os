"""Libri pokretač — Veritasove faze kao jedan deterministički tok (ADR-0123).

Ceo tok nad uvezenim dokumentom umesto četiri ručne komande:
  Čitač (tvrdnje) → Kartograf/Hroničar (entiteti) → Proveravač (pouzdanost)
  → Bibliotekar (dosije)
sa Čuvar-invarijantom (izvor + blokovi; licenca je gejtovana na uvozu,
ADR-0074) i jasnim zaustavljanjem ako faza padne.

Ne koristi `AgentPlan`: mašina planova (ADR-0021) je vezana za personu, a Libri
je sloj znanja bez persone. Zato zaseban, scope-ovan pokretač koji prati ADR-0021
obrazac (faze → ishod → zaustavljanje sa razlogom), a ne njegove modele
(ADR-0123). Faze su idempotentne (svaki `upisi` je delete+recreate po izvoru),
pa je ponovno pokretanje bezbedno. Zove se unutar `bind(actor)` (komanda to
obezbeđuje). LLM faze (hipoteze, otvorena pitanja — dosije §9/§10) ulaze kasnije
iza istih potpisa, bez promene toka.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from apps.libri import dosije, entiteti, pouzdanost, tvrdnje


class LibriPlanError(Exception):
    """Faza nije mogla da se završi; tok staje sa imenom faze i razlogom."""

    def __init__(self, faza: str, razlog: str):
        super().__init__(f"{faza}: {razlog}")
        self.faza, self.razlog = faza, razlog


@dataclass(frozen=True)
class Faza:
    naziv: str
    opis: str
    izvrsi: Callable[..., dict]


def _citac(document) -> dict:
    r = tvrdnje.upisi(document)
    return {"tvrdnje": r["upisano"]}


def _kartograf(document) -> dict:
    r = entiteti.upisi(document)
    return {"entiteti": r["entiteta"], "odnosi": r["odnosa"]}


def _proveravac(document) -> dict:
    r = pouzdanost.upisi(document)
    return {"ocenjeno": r["ocenjeno"]}


def _bibliotekar(document) -> dict:
    md = dosije.sastavi(document)
    return {"dosije_duzina": len(md), "dosije": md}


#: Veritasove faze mapirane na deterministički Libri sloj (ADR-0031 §1).
FAZE: list[Faza] = [
    Faza("Čitač", "tvrdnje iz blokova (sloj 4a)", _citac),
    Faza("Kartograf+Hroničar", "entiteti, odnosi, dvostruko vreme (4b)", _kartograf),
    Faza("Proveravač", "pouzdanost po pet osa (4b+)", _proveravac),
    Faza("Bibliotekar", "dosije, 12 sekcija (4c)", _bibliotekar),
]


def _cuvar(document) -> None:
    """Invarijanta pre toka: izvor i blokovi postoje (licenca gejtovana na uvozu)."""
    if document.source is None:
        raise LibriPlanError("Čuvar", "dokument nema izvor (KnowledgeSource)")
    if not document.blocks.exists():
        raise LibriPlanError("Čuvar", "dokument nema blokove (uvezi/reindeksiraj prvo)")


def pokreni(document) -> dict:
    """Pokreni ceo Libri tok nad dokumentom (zove se unutar `bind(actor)`).

    Vraća {"faze": [{"naziv", "rezultat"}…], "dosije": <markdown>}. Faza koja
    padne (`ValueError` iz upisa) zaustavlja tok uz `LibriPlanError` — nikad tiho.
    """
    _cuvar(document)
    faze: list[dict] = []
    dosije_md = ""
    for f in FAZE:
        try:
            out = f.izvrsi(document)
        except ValueError as e:
            raise LibriPlanError(f.naziv, str(e)) from e
        dosije_md = out.pop("dosije", "") or dosije_md
        faze.append({"naziv": f.naziv, "rezultat": out})
    return {"faze": faze, "dosije": dosije_md}
