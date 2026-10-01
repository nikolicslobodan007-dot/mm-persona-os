"""Priručnik radnog mesta — kako se ovde radi ovaj posao. ADR-0060.

Pouka urednika (ADR-0014) kaže šta je jedan agent naučio iz jednog odbijanja.
Dozvola (ADR-0017, ADR-0037) kaže šta sme. Između ta dva je falio treći sloj, i
to baš onaj koji opisuje **zanat**: kako se ovde piše zakrpa, kako se izviđa,
kako se gleda licenca. To ne visi o agentu nego o stolici.

## Tri stvari koje ovaj modul radi drugačije od `lessons.py`

- **Ključ, ne tekst.** Pouka se prepoznaje po tekstu, pa se isti upis dvaput
  razlikuje po zarezu. Pravilo priručnika ima stabilan ključ: po njemu se
  prepisuje i po njemu se gasi, pa ispravka formulacije ne pravi duplikat.
- **Redosled je deo sadržaja.** Pouke idu „najnovije prve"; pravila priručnika
  se čitaju kao numerisan spisak i prvo pravilo nije slučajno prvo.
- **Izvor se čuva, ali ne ide u prompt** (ADR-0060 §3 traži zapis, ne prompt).
  Agent ne može da otvori `docs/adr/` — to je zaštićena zona i nije u brifu
  (ADR-0061) — pa bi citat u promptu bio ukras koji jede mesto zadatku.
  Izmereno nad jezgrom `RAZ-PRO`: izvori su 345 znakova, 23 % celog odeljka.

## Plafon

Priručnik ulazi u prompt za **kod**, a ne u prompt za sadržaj. To su dva
različita plafona i ADR-0063 je napisan zato što smo ih pobrkali: pouke
urednika (`PROMPT_BUDGET_CHARS = 4000`) ne ulaze u `pisac._prompt` uopšte.
Pravi plafon ovde je brif (`MAX_TOTAL_BYTES`), a `PRIRUCNIK_BUDGET_CHARS` je
granica rasta samog priručnika — da jedan opis posla ne bi vremenom pojeo
prostor koji treba fajlovima.

Ako nešto ne stane, to se **kaže** u promptu. Ćutke skraćen spisak pravila je
gori od kratkog: agent po njemu radi kao da je potpun (ADR-0033, ADR-0036 §1).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from api import audit

from .models import Position, PositionHandbookRule

__all__ = ["Pravilo", "upisi", "spisak", "ugasi", "prompt_section", "mesto_persone",
           "PRIRUCNIK_BUDGET_CHARS", "ODSECENO"]

#: Gornja granica odeljka priručnika u promptu, u znakovima. Nije procena
#: potrebe nego granica rasta: jezgro `RAZ-PRO` je izmereno na 1502 znaka, pa
#: ovo ostavlja prostor za dopune a i dalje je ispod 1 % plafona brifa.
PRIRUCNIK_BUDGET_CHARS = 3000

#: Rečenica koja stoji umesto odsečenih pravila.
ODSECENO = "- [odsečeno: još {broj} pravila nije stalo u prompt]"

NASLOV = "## priručnik radnog mesta {mesto} — ovako se ovde radi"


@dataclass(frozen=True)
class Pravilo:
    """Jedno pravilo kakvo ga čovek predaje komandi ili `seed`-u."""

    kljuc: str
    redosled: int
    tekst: str
    izvor: str


def _mesto(kod: str) -> Position:
    p = Position.objects.filter(code=kod).first()
    if p is None:
        raise ValueError(f"Radno mesto {kod!r} ne postoji.")
    return p


@transaction.atomic
def upisi(kod_mesta: str, pravila: list[Pravilo], *, actor: str) -> dict[str, int]:
    """Upisuje jezgro priručnika. Idempotentno po ključu.

    Ne dira pravila koja nisu u predatom spisku — gašenje ide kroz `ugasi`, uz
    razlog. Tiho nestalo pravilo bi bilo izmena opisa posla koju niko nije
    potpisao.
    """
    mesto = _mesto(kod_mesta)
    br = {"upisano": 0, "izmenjeno": 0, "netaknuto": 0}
    for p in pravila:
        if not p.izvor.strip():
            raise ValueError(f"Pravilo {p.kljuc!r} nema izvor (ADR-0060 §3).")
        red = PositionHandbookRule.objects.filter(position=mesto, key=p.kljuc).first()
        if red is None:
            PositionHandbookRule.objects.create(
                position=mesto, key=p.kljuc, text=p.tekst, source=p.izvor,
                sort_order=p.redosled, created_by=actor[:120])
            br["upisano"] += 1
            continue
        if (red.text, red.source, red.sort_order, red.is_active) == (
                p.tekst, p.izvor, p.redosled, True):
            br["netaknuto"] += 1
            continue
        red.text, red.source, red.sort_order = p.tekst, p.izvor, p.redosled
        # Ponovni upis vraća u život pravilo koje je neko ugasio, pa se razlog
        # gašenja briše zajedno sa potpisom — inače bi ostao da visi uz pravilo
        # koje ponovo važi i lagao bi istoriju.
        red.is_active, red.retired_reason, red.retired_by = True, "", ""
        red.save(update_fields=["text", "source", "sort_order", "is_active",
                                "retired_reason", "retired_by", "updated_at"])
        br["izmenjeno"] += 1

    audit.record("personas.handbook.written",
                 details={"mesto": kod_mesta, "actor": actor, **br})
    return br


def spisak(kod_mesta: str, *, i_ugasena: bool = False) -> list[PositionHandbookRule]:
    """Pravila mesta, redom kojim se čitaju."""
    qs = PositionHandbookRule.objects.filter(position__code=kod_mesta)
    if not i_ugasena:
        qs = qs.filter(is_active=True)
    return list(qs.order_by("sort_order", "key"))


@transaction.atomic
def ugasi(kod_mesta: str, kljuc: str, *, razlog: str, actor: str) -> PositionHandbookRule:
    """Gasi pravilo. Bez razloga se ne gasi (ADR-0036 §1)."""
    if not razlog.strip():
        raise ValueError("Gašenje pravila traži razlog.")
    red = PositionHandbookRule.objects.filter(
        position__code=kod_mesta, key=kljuc).first()
    if red is None:
        raise ValueError(f"Mesto {kod_mesta!r} nema pravilo {kljuc!r}.")
    red.is_active, red.retired_reason, red.retired_by = False, razlog[:300], actor[:120]
    red.save(update_fields=["is_active", "retired_reason", "retired_by", "updated_at"])
    audit.record("personas.handbook.retired",
                 details={"mesto": kod_mesta, "kljuc": kljuc,
                          "razlog": razlog[:300], "actor": actor})
    return red


def mesto_persone(persona) -> str | None:
    """Šifra radnog mesta na kom agent sedi sada, ili `None`.

    Gleda se otvoren primarni raspored (`Assignment`), ne istorija: priručnik
    važi za stolicu na kojoj agent sedi danas. Ko pređe na drugo mesto, dobija
    drugi priručnik istog dana — to je i razlog što priručnik ne visi o agentu
    (ADR-0060 §1).
    """
    if persona is None:
        return None
    red = (persona.assignments
           .filter(ended_at__isnull=True, is_primary=True)
           .select_related("position").first())
    return red.position.code if red else None


def prompt_section(kod_mesta: str, *, budzet: int = PRIRUCNIK_BUDGET_CHARS) -> str:
    """Odeljak priručnika za prompt, sa gornjom granicom u znakovima.

    Izvori ne ulaze (ADR-0060 §3, ADR-0063 §2). Ono što ne stane se kaže.
    """
    pravila = spisak(kod_mesta)
    if not pravila:
        return ""

    naslov = NASLOV.format(mesto=kod_mesta)
    redom = [f"{i}. {r.text}" for i, r in enumerate(pravila, start=1)]

    # Red o odsecanju mora da stane U budžet, ne pored njega — isto kao kod
    # pouka (`lessons.ODSECENO`). Mesto mu se rezerviše unapred, po najvećem
    # mogućem broju, da punjenje ne bi probilo budžet dodavanjem tog reda na
    # kraju.
    rezerva = len(ODSECENO.format(broj=len(redom))) + 1 if redom else 0

    stalo: list[str] = []
    zauzeto = len(naslov)
    for red in redom:
        if zauzeto + 1 + len(red) + rezerva > budzet:
            break
        stalo.append(red)
        zauzeto += 1 + len(red)

    odseceno = len(redom) - len(stalo)
    if odseceno:
        stalo.append(ODSECENO.format(broj=odseceno))
    return "\n".join([naslov, *stalo])
