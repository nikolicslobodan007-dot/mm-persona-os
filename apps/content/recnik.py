"""Rečnik uz Pravopis kao znanje i kao provera. ADR-0055.

Kućni stil (ADR-0054) nosi šest pravila u svaki prompt. Rečnik je druga stvar:
8.797 odrednica ne staje ni u jedan prompt i ne treba da staje. On radi na
izlazu — kad nacrt izađe iz modela, proverava se nad oblicima koje knjiga
**izričito odbija** („avlija, ne havlija"). Ta provera ne zove model, ne košta
ništa i uz svaki nalaz stoji odrednica i broj tačke.

Šta je u bazi: jedan `KnowledgeSource` (deljen, `persona=NULL`) i po jedna
`KnowledgeFact` za svaku odrednicu, `predicate="pravopis.odrednica"`.

O brojevima tačaka — ono što je ovde najvažnije. Deo PRAVILA ide do tačke 322.
Upućivanje veće od toga („т. 854") nastalo je tako što je OCR pročitao slovo
pod-tačke kao cifru, pa se spušta na samu tačku. Gore je kad cifra padne u
opseg: knjiga piše „т. 27b", OCR daje „т. 276", a 276 je stvarna tačka o
sasvim drugoj stvari. Takvih 620 **nema broj tačke** — u tekstu im stoji
„t. [nejasno: 276 ili 27b]". Bolje bez upućivanja nego sa pogrešnim; ADR-0033.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.db import transaction

from api import audit
from apps.content.pravopis import DONJI, GORNJI
from apps.memory.models import KnowledgeFact, KnowledgeSource
from common import enums as E

#: Naslov po kome se izvor pronalazi — i jedini ključ za idempotentan uvoz.
IZVOR = "Rečnik uz Pravopis srpskoga jezika (Matica srpska)"
PREDIKAT = "pravopis.odrednica"

#: Datoteka iz koje se uvozi. Napravljena je skriptovima u `tools/pravopis/`;
#: u repozitorijumu stoji da se uvoz može ponoviti bez skeniranja knjige.
DATOTEKA = Path(__file__).resolve().parent / "data" / "recnik-uz-pravopis.jsonl"


@dataclass(frozen=True)
class Nalaz:
    """Jedan oblik u tekstu koji knjiga odbija."""

    oblik: str          # ono što je napisano
    odrednica: str      # odrednica koja ga odbija
    tekst: str          # šta odrednica kaže
    tacke: tuple[str, ...]

    def __str__(self) -> str:
        rep = f" (Pravopis, t. {', '.join(self.tacke)})" if self.tacke else ""
        return f"{DONJI}{self.oblik}{GORNJI} — {self.tekst}{rep}"


# ----------------------------------------------------------------- uvoz

def uvezi(*, actor: str = "user:slobodan", putanja: Path | None = None) -> dict[str, int]:
    """Upisuje Rečnik u `KnowledgeSource`/`KnowledgeFact`. Vraća prebrojano.

    Ponovni uvoz **briše i upisuje ponovo**. Knjiga se ne menja, pa spajanje
    red po red ne bi ništa dobilo, a ostavilo bi odrednice iz ranije, lošije
    obrade da žive pored novih — a upravo je jedna takva obrada i odbačena
    (ADR-0055). Sve je u jednoj transakciji.
    """
    putanja = putanja or DATOTEKA
    redovi = [json.loads(r) for r in putanja.read_text(encoding="utf-8").splitlines() if r]
    with transaction.atomic():
        izvor, _ = KnowledgeSource.objects.get_or_create(
            persona=None, title=IZVOR,
            defaults={"source_kind": E.SourceKind.FIRST_PARTY_USER_INPUT.value,
                      "trust_score": 1.0, "uri": "", "is_active": True})
        obrisano = KnowledgeFact.objects.filter(source=izvor, predicate=PREDIKAT).delete()[0]
        KnowledgeFact.objects.bulk_create([
            KnowledgeFact(
                source=izvor, persona=None, subject=r["odrednica"][:220],
                predicate=PREDIKAT, provenance=E.Provenance.USER_PROVIDED.value,
                confidence=1.0,
                object_json={"tekst": r["tekst"], "tekst_cir": r["tekst_cir"],
                             "odrednica_cir": r["odrednica_cir"], "tacke": r["tacke"],
                             "strana": r["strana_pdf"], "ne": r["ne"]})
            for r in redovi
        ], batch_size=1000)
    broj = {"upisano": len(redovi), "obrisano": obrisano,
            "sa tačkom": sum(1 for r in redovi if r["tacke"]),
            "odbijenih oblika": sum(len(r["ne"]) for r in redovi)}
    audit.record("content.recnik.loaded", details={"izvor": IZVOR, "actor": actor, **broj})
    _zabranjeni.cache_clear()
    return broj


# --------------------------------------------------------------- traženje

def _kljuc(rec: str) -> str:
    """Bez dijakritika i bez velikih slova — da „Đačko" nađe „đački"."""
    razlozeno = unicodedata.normalize("NFD", rec.lower())
    bez = "".join(z for z in razlozeno if not unicodedata.combining(z))
    return bez.replace("đ", "d").replace("Đ", "d").strip()


#: Najkraća osnova koja se sme porediti. Ispod ovoga bi „ne-" hvatalo pola
#: rečnika.
MIN_OSNOVA = 4
SAMOGLASNICI = "aeiou"


def _osnova(rec: str) -> str:
    """Reč bez nastavka — koliko je potrebno da „havliju" pogodi „havlija".

    Srpski menja reč po padežima, a rečnik daje nominativ. Bez ovoga provera
    hvata samo tekst u kojem zabranjeni oblik stoji baš u osnovnom obliku, što
    u rečenici skoro nikad nije slučaj.

    **Dijakritici se zadržavaju.** Prvo sam ih skidao, kao kod traženja, i
    provera je onda „podaci" prijavljivala kao „podaći" iz odrednice „podići,
    bolje nego podaći" — a to su dve različite reči i razlika je baš u kvačici.
    Kod traženja je tolerancija korisna, ovde je greška.

    Seče se najviše dva završna samoglasnika. To je grubo — nije morfologija
    nego skraćivanje — pa provera **prijavljuje**, ne obara nacrt.
    """
    k = rec.lower().strip()
    for _ in range(2):
        if len(k) > MIN_OSNOVA and k[-1] in SAMOGLASNICI:
            k = k[:-1]
    return k


def nadji(rec: str, *, granica: int = 10) -> list[dict]:
    """Odrednice za jednu reč. Prvo tačan pogodak, pa početak reči."""
    rec = rec.strip()
    if not rec:
        return []
    qs = KnowledgeFact.objects.filter(persona__isnull=True, predicate=PREDIKAT)
    tacni = list(qs.filter(subject__iexact=rec)[:granica])
    if len(tacni) < granica:
        ostatak = qs.filter(subject__istartswith=rec).exclude(
            pk__in=[f.pk for f in tacni])[:granica - len(tacni)]
        tacni += list(ostatak)
    return [{"odrednica": f.subject, **f.object_json} for f in tacni]


# ---------------------------------------------------------------- provera

@dataclass(frozen=True)
class _Zabrana:
    odrednica: str
    tekst: str
    tacke: tuple[str, ...]
    veliko: bool        # oblik je u knjizi napisan velikim slovom (ime)


@lru_cache(maxsize=1)
def _zabranjeni() -> dict[str, _Zabrana]:
    """{osnova oblika: zabrana} — učitava se jednom po procesu."""
    mapa: dict[str, _Zabrana] = {}
    for f in KnowledgeFact.objects.filter(
            persona__isnull=True, predicate=PREDIKAT).exclude(object_json__ne=[]):
        tiho = {_osnova(o) for o in f.object_json.get("tiho", ())}
        for oblik in f.object_json.get("ne", ()):
            k = _osnova(oblik)
            if k in tiho:
                continue
            mapa.setdefault(k, _Zabrana(
                f.subject, f.object_json.get("tekst", ""),
                tuple(f.object_json.get("tacke", ())), oblik[:1].isupper()))
    return mapa


def utisaj(oblik: str, *, actor: str, razlog: str) -> int:
    """Isključuje jedan oblik iz provere. Vraća koliko je odrednica dirnuto.

    Spisak zabranjenih oblika je izveden obrascem iz teksta odrednica, pa u
    njemu ima i reči koje knjiga odbija samo u jednom značenju („mahala, ne
    mala"). Takav oblik se ne briše iz odrednice — odrednica je tačna — nego
    mu se ukida dejstvo u proveri, sa razlogom u zapisu.
    """
    if not razlog.strip():
        raise ValueError("Uz utišavanje ide razlog.")
    dirnuto = 0
    for f in KnowledgeFact.objects.filter(
            persona__isnull=True, predicate=PREDIKAT).exclude(object_json__ne=[]):
        if not any(_osnova(o) == _osnova(oblik) for o in f.object_json.get("ne", ())):
            continue
        tiho = sorted({*f.object_json.get("tiho", ()), oblik.lower()})
        f.object_json = {**f.object_json, "tiho": tiho}
        f.save(update_fields=["object_json", "updated_at"])
        dirnuto += 1
    audit.record("content.recnik.form_silenced",
                 details={"oblik": oblik, "razlog": razlog.strip()[:500],
                          "actor": actor, "odrednica": dirnuto})
    _zabranjeni.cache_clear()
    return dirnuto


REC = re.compile(r"[^\W\d_]+", re.UNICODE)


def proveri(tekst: str) -> list[Nalaz]:
    """Oblici u tekstu koje Pravopis izričito odbija.

    Deterministički i bez modela: poredi se reč po reč sa spiskom oblika koje
    odrednice odbijaju rečima „ne X" ili „bolje nego X". Spisak je izveden
    obrascem iz teksta odrednica, pa ume da pogreši — zato ovo **prijavljuje**,
    ne obara nacrt. Odluku donosi urednik, i vidi odrednicu uz nalaz.

    Veliko slovo se poštuje. Odrednica „Koraks (ne Korak)" govori o prezimenu;
    da se gleda samo osnova, provera bi prijavljivala svaki „korak" u tekstu —
    i jeste, 45 puta na 36.733 reči naših ADR-ova, dok to nije ispravljeno.
    """
    zabranjeni = _zabranjeni()
    nalazi: list[Nalaz] = []
    vidjeni: set[str] = set()
    for m in REC.finditer(tekst):
        rec = m.group(0)
        k = _osnova(rec)
        z = zabranjeni.get(k)
        if z is None or k in vidjeni or (z.veliko and not rec[:1].isupper()):
            continue
        vidjeni.add(k)
        nalazi.append(Nalaz(rec, z.odrednica, z.tekst, z.tacke))
    return nalazi
