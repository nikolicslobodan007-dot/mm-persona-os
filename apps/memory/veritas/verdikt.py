"""Veritas — verdikt motor: tvrdnja + izvori → ocena po pet osa + verdikt.

Reuse Libri `pouzdanost.oceni()` (ADR-0031 §4b, čista funkcija): svaki izvor nosi
stav (potvrđuje / oponira) prema tvrdnji, i metapodatke (vrsta → source_kind za
blizinu, trust). Ose:
  pouzdanost (trust izvora), blizina (prvoručno vs posredno), potkrepljenost
  (koliko DRUGIH saglasnih), nezavisnost (koliko RAZLIČITIH saglasnih),
  stabilnost (pada ako ima protivrečnih).

Time se honoruju oba pravila deska: „više strana" (potkrepljenost+nezavisnost) i
„ljudski svedok" (vrsta `svedok` → first_party_user_input, blizina 0.90).
Veritas i dalje NE bira pobednika među protivrečnima (ADR-0006): kad ih ima,
verdikt je DELIMIČNO, a ose to pokažu.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from apps.libri import pouzdanost

POTVRDJUJE = "potvrdjuje"
OPONIRA = "oponira"
#: izvor potvrđuje da je IZREČENO, ali spori TUMAČENJE (npr. „izvučeno iz konteksta")
SPORNO = "potvrdjuje_sporno_tumacenje"
_SAGLASNI = {POTVRDJUJE, SPORNO}  # oba potvrđuju da je izrečeno/dogodilo se
_PREDIKAT = "veritas.ocena"

# vrsta izvora → source_kind (ulaz u blizinu iz pouzdanosti)
_VRSTA_KIND = {
    "svedok": "first_party_user_input",   # ljudski očevidac — blizina 0.90
    "redakcija": "public_web_source",
    "web": "public_web_source",
    "tabloid": "public_web_source",
}
_PODRAZUMEVANI_TRUST = {"svedok": 0.9, "redakcija": 0.7, "web": 0.5, "tabloid": 0.3}


def _kljuc(tvrdnja: str) -> str:
    h = hashlib.sha1(tvrdnja.strip().lower().encode("utf-8")).hexdigest()
    return "tvr:" + h[:12]


def _fact(kljuc: str, izvor: dict, i: int) -> SimpleNamespace:
    vrsta = izvor.get("vrsta", "web")
    stav = izvor.get("stav", POTVRDJUJE)
    vrednost = POTVRDJUJE if stav in _SAGLASNI else OPONIRA
    trust = float(izvor.get("trust", _PODRAZUMEVANI_TRUST.get(vrsta, 0.5)))
    return SimpleNamespace(
        subject=kljuc, predicate=_PREDIKAT, vrednost=vrednost,
        trust=trust, source_kind=_VRSTA_KIND.get(vrsta, "public_web_source"),
        source_id=str(izvor.get("id", f"{vrsta}-{i}")),
    )


def _verdikt(saglasnih: int, protivrecnih: int, ukupno: float) -> str:
    if saglasnih == 0 and protivrecnih == 0:
        return "NEDOVOLJNO"
    if saglasnih and protivrecnih:
        return "DELIMIČNO"
    if protivrecnih and not saglasnih:
        return "NEPOTVRĐENO"
    if ukupno >= 0.75:
        return "POTVRĐENO"
    if ukupno >= 0.55:
        return "VEROVATNO"
    return "NEDOVOLJNO"


def oceni_tvrdnju(tvrdnja: str, izvori: list[dict]) -> dict:
    """`izvori`: [{vrsta, stav, trust?, id?}]. Vrati verdikt + ose + brojeve."""
    kljuc = _kljuc(tvrdnja)
    sporno = sum(1 for iz in izvori if iz.get("stav") == SPORNO)
    facts = [_fact(kljuc, iz, i) for i, iz in enumerate(izvori)]
    if not facts:
        return {"verdikt": "NEDOVOLJNO", "ose": None, "izvori": 0,
                "saglasnih": 0, "protivrecnih": 0, "sporno_tumacenje": 0}
    saglasni = [f for f in facts if f.vrednost == POTVRDJUJE]
    protivrecni = [f for f in facts if f.vrednost == OPONIRA]
    # tv = najjači saglasni (svedok pa po trust-u); ako nema saglasnih, prvi protivrečni
    if saglasni:
        tv = max(saglasni, key=lambda f: (f.source_kind == "first_party_user_input",
                                          f.trust))
    else:
        tv = protivrecni[0]
    ose = pouzdanost.oceni(tv, facts)
    verdikt = _verdikt(len(saglasni), len(protivrecni), ose["ukupno"])
    return {"verdikt": verdikt, "ose": ose, "izvori": len(facts),
            "saglasnih": len(saglasni), "protivrecnih": len(protivrecni),
            "sporno_tumacenje": sporno}
