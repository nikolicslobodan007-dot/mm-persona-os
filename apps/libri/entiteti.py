"""Entiteti i graf odnosa iz Libri blokova (ADR-0031 sloj 4b).

Blok → entiteti (osoba / organizacija / događaj) + odnosi (subjekat → objekat sa
tipom veze) → `Entitet`/`Odnos`. Ekstraktor je **zamenljiv sloj** (Canon §21):
deterministička osnova sada (imenovani entiteti po pokaznim rečima + mali skup
relacionih obrazaca), a LLM kasnije ulazi kroz isti potpis `izvuci_*(blocks)`.

Visoka preciznost, niži odziv — donja granica pre LLM-a: entitet se pravi samo kad
postoji jasna pokazna reč (kompanija/preduzeće za organizaciju, ime i prezime ili
uloga za osobu, događaj + glagol/datum za događaj), a odnos samo između dva VEĆ
prepoznata entiteta (zato „Brušenje se radi u nekoliko prolaza" ne pravi lažan
odnos). Vrsta se određuje po SUSEDNIM rečima, ne po celoj rečenici — da osoba i
organizacija u istoj rečenici ne dobiju istu vrstu. Dvostruko vreme (ADR-0031
§3.2): događaj nosi `desilo_se` (datum u rečenici) i `objavljeno` (kad ga izvor
da) — dva polja, ne jedno.

Provenance je `OBSERVED`: doslovno navedeno u izvoru; poreklo ide do bloka
(`object_json.block_id`). Upis je delete+recreate po izvoru (obrazac `tvrdnje`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from typing import Any

VRSTE = ("osoba", "organizacija", "dogadjaj")
TIPOVI_ODNOSA = ("radi_u", "vodi", "deo_od", "nalazi_se_u", "osnovao")

# Granica rečenice: `.!?` + razmak + veliko slovo (ili kraj) — tako datum
# „12.03.2026." i skraćenica „d.o.o." ostaju celi, ne cepaju se po tačkama.
_GRANICA = re.compile(r"(?<=[.!?])\s+(?=[A-ZČĆŽŠĐ])")
_TOKEN = r"[A-ZČĆŽŠĐ][\wčćžšđ.-]*"
_DATUM = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b")

# Pokazne reči (mala slova) — vezuju susedni naziv za vrstu.
_ORG_CUE = frozenset((
    "kompanija", "kompaniju", "kompanije", "kompaniji", "preduzeće", "preduzeća",
    "preduzeću", "firma", "firme", "firmu", "firmi", "udruženje", "udruženja",
    "udruženju", "institut", "instituta", "fakultet", "ministarstvo", "agencija",
    "agenciju", "agencije", "društvo", "društva",
))
_ORG_SUFFIX = frozenset(("doo", "d.o.o", "ad", "a.d"))
_OSOBA_CUE = frozenset((
    "direktor", "direktorka", "direktora", "direktorke", "predsednik",
    "predsednica", "profesor", "profesorka", "gospodin", "gospođa", "rođen",
    "rođena", "osnivač", "osnivačica",
))
_DOGADJAJ_CUE = frozenset((
    "konferencija", "konferencije", "kongres", "samit", "sastanak", "događaj",
    "radionica", "sajam", "svečanost",
))
_DOGADJAJ_GLAGOL = frozenset((
    "održan", "održana", "održano", "osnovan", "osnovana", "potpisan",
    "potpisana", "otvoren", "otvorena",
))
# Golo „ime prezime" postaje osoba SAMO uz relacioni kontekst (glagol iza imena),
# da nabrajanja u literaturi/citatima („Literatura Hidrotermička", „Kolin
# Beograd") ne prođu kao osobe — izmereno na stvarnom dokumentu (ADR-0033).
_OSOBA_GLAGOL = frozenset((
    "radi", "zaposlen", "zaposlena", "je", "su", "vodi", "osnovao", "osnovala",
    "rukovodi", "predsedava",
))

# Relacioni obrasci nad rečenicom: grupe 1 i 2 su nazivi entiteta.
_ODNOSI = (
    (re.compile(rf"({_TOKEN}(?:\s+{_TOKEN}){{0,2}})\s+(?:radi|zaposlen[a]?)\s+u\s+"
                rf"(?:kompaniji|preduzeću|firmi)?\s*({_TOKEN}(?:\s+{_TOKEN}){{0,2}})"),
     "radi_u"),
    (re.compile(rf"({_TOKEN}(?:\s+{_TOKEN}){{0,2}})\s+je\s+(?:direktor|direktorka)\s+"
                rf"(?:kompanije|preduzeća|firme)?\s*({_TOKEN}(?:\s+{_TOKEN}){{0,2}})"),
     "vodi"),
    (re.compile(rf"({_TOKEN}(?:\s+{_TOKEN}){{0,2}})\s+deo\s+je\s+"
                rf"(?:udruženja|kompanije|preduzeća)?\s*({_TOKEN}(?:\s+{_TOKEN}){{0,2}})"),
     "deo_od"),
    (re.compile(rf"({_TOKEN}(?:\s+{_TOKEN}){{0,2}})\s+se\s+nalazi\s+u\s+"
                rf"({_TOKEN}(?:\s+{_TOKEN}){{0,2}})"),
     "nalazi_se_u"),
    (re.compile(rf"({_TOKEN}(?:\s+{_TOKEN}){{0,2}})\s+je\s+osnova[ol]a?\s+"
                rf"(?:kompaniju|preduzeće|firmu)?\s*({_TOKEN}(?:\s+{_TOKEN}){{0,2}})"),
     "osnovao"),
)


def _recenice(text: str) -> list[str]:
    return [r.strip() for r in _GRANICA.split(text or "") if r.strip()]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _gol(tok: str) -> str:
    """Token bez okolne interpunkcije (zadrži unutrašnje tačke: d.o.o.)."""
    return tok.strip(".,;:!?()\"'„”…")


def _cap(tok: str) -> bool:
    t = _gol(tok)
    return bool(t) and t[0] in "ABCČĆDĐEFGHIJKLMNOPRSŠTUVZŽ"


def _datum(recenica: str):
    m = _DATUM.search(recenica)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _vrsta(span_tokens: list[str], prev: str, nxt: str) -> str | None:
    """Vrsta po susednim rečima i obliku naziva; bez jasne pokazne → None."""
    low = [_gol(t).lower() for t in span_tokens]
    if prev in _ORG_CUE or low[0] in _ORG_CUE or low[-1] in _ORG_SUFFIX:
        return "organizacija"
    if low[0] in _DOGADJAJ_CUE or nxt in _DOGADJAJ_GLAGOL:
        return "dogadjaj"
    if prev in _OSOBA_CUE:
        return "osoba"
    if (len(span_tokens) == 2 and nxt in _OSOBA_GLAGOL and all(
        re.fullmatch(r"[A-ZČĆŽŠĐ][a-zčćžšđ]+", _gol(t)) for t in span_tokens
    )):
        return "osoba"
    return None


def _spanovi(rec: str):
    """Vrati (naziv, [tokeni], prev, next) za svaki niz velikih tokena (1–3)."""
    toks = rec.split()
    i = 0
    while i < len(toks):
        if _cap(toks[i]):
            j = i
            while j + 1 < len(toks) and _cap(toks[j + 1]) and (j - i) < 2:
                j += 1
            span_tokens = [_gol(t) for t in toks[i:j + 1]]
            naziv = _norm(" ".join(span_tokens))
            prev = _gol(toks[i - 1]).lower() if i > 0 else ""
            nxt = _gol(toks[j + 1]).lower() if j + 1 < len(toks) else ""
            yield naziv, span_tokens, prev, nxt
            i = j + 1
        else:
            i += 1


def izvuci_entitete(blocks: Iterable[Any]) -> list[dict]:
    """Vrati kandidat-entitete iz blokova (čista funkcija, bez baze)."""
    out: list[dict] = []
    vidjeni: set[tuple[str, str]] = set()
    for b in blocks:
        if getattr(b, "block_type", "") != "paragraph":
            continue
        for rec in _recenice(getattr(b, "text", "")):
            datum = _datum(rec)
            for naziv, span_tokens, prev, nxt in _spanovi(rec):
                if len(naziv) < 2:
                    continue
                vrsta = _vrsta(span_tokens, prev, nxt)
                if vrsta is None:
                    continue
                key = (vrsta, naziv.lower())
                if key in vidjeni:
                    continue
                vidjeni.add(key)
                out.append({
                    "name": naziv[:220], "kind": vrsta, "normalized": naziv.lower()[:220],
                    "block_id": getattr(b, "block_id", ""),
                    "source_page": getattr(b, "source_page", None),
                    "desilo_se": datum.isoformat() if (vrsta == "dogadjaj" and datum) else None,
                    "objavljeno": None,
                    "confidence": 0.6,
                })
    return out


def izvuci_odnose(blocks: Iterable[Any], entiteti: list[dict]) -> list[dict]:
    """Odnos samo između dva VEĆ prepoznata entiteta (visoka preciznost)."""
    imena = {e["normalized"] for e in entiteti}
    out: list[dict] = []
    vidjeni: set[tuple[str, str, str]] = set()
    for b in blocks:
        if getattr(b, "block_type", "") != "paragraph":
            continue
        for rec in _recenice(getattr(b, "text", "")):
            for rx, tip in _ODNOSI:
                m = rx.search(rec)
                if not m:
                    continue
                subj = _norm(" ".join(_gol(t) for t in m.group(1).split()))
                obj = _norm(" ".join(_gol(t) for t in m.group(2).split()))
                if subj.lower() not in imena or obj.lower() not in imena:
                    continue
                key = (subj.lower(), tip, obj.lower())
                if key in vidjeni:
                    continue
                vidjeni.add(key)
                out.append({
                    "subject": subj, "object": obj, "relation_type": tip,
                    "block_id": getattr(b, "block_id", ""),
                    "source_page": getattr(b, "source_page", None),
                    "confidence": 0.6,
                })
    return out


def upisi(document) -> dict[str, int]:
    """Izvuci entitete i odnose iz blokova dokumenta i upiši ih.

    Vezuje se za dokumentov `KnowledgeSource`. Delete+recreate po izvoru (isti
    obrazac kao `tvrdnje`). Jedna transakcija; zove se unutar `bind(actor)`.
    """
    from datetime import datetime

    from django.db import transaction
    from django.utils.timezone import make_aware

    from apps.libri.models import Entitet, Odnos

    izvor = document.source
    if izvor is None:
        raise ValueError(
            f"Dokument {document.document_id} nema izvor (KnowledgeSource) — "
            "entitet ne sme da postoji bez izvora (Canon §4.1)."
        )
    blokovi = list(document.blocks.all())
    kand_e = izvuci_entitete(blokovi)
    kand_o = izvuci_odnose(blokovi, kand_e)

    def _dt(iso):
        return make_aware(datetime.fromisoformat(iso + "T00:00:00")) if iso else None

    with transaction.atomic():
        stari_o = Odnos.objects.filter(source=izvor)
        stari_e = Entitet.objects.filter(source=izvor)
        obrisano = stari_o.count() + stari_e.count()
        stari_o.delete()
        stari_e.delete()
        po_nazivu: dict[str, Entitet] = {}
        for k in kand_e:
            ent = Entitet.objects.create(
                source=izvor, kind=k["kind"], name=k["name"],
                normalized=k["normalized"], aliases=[],
                desilo_se=_dt(k["desilo_se"]), objavljeno=_dt(k["objavljeno"]),
                confidence=k["confidence"],
                object_json={"block_id": k["block_id"], "source_page": k["source_page"]},
            )
            po_nazivu[k["normalized"]] = ent
        odnosi = []
        for k in kand_o:
            subj = po_nazivu.get(k["subject"].lower())
            obj = po_nazivu.get(k["object"].lower())
            if subj is None or obj is None:
                continue
            odnosi.append(Odnos(
                source=izvor, subject=subj, object=obj,
                relation_type=k["relation_type"], confidence=k["confidence"],
                object_json={"block_id": k["block_id"], "source_page": k["source_page"]},
            ))
        Odnos.objects.bulk_create(odnosi)
    return {"entiteta": len(po_nazivu), "odnosa": len(odnosi), "obrisano": obrisano}
