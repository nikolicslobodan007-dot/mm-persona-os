"""Šef pregleda nacrt pre nego što ga vrati nalogodavcu. ADR-0108.

Do danas je šef sektora bio poštar: primio je posao od direktora, zadao ga
izvršiocu i vratio ono što je dobio, nepročitano. Korak kojim je „preuzimao
gotov posao" (`plan.note`) po projektu ne radi ništa.

Ovde šef dobija jedan stvaran posao: da **pročita** nacrt i kaže da li ga
prihvata. Tri granice, namerno:

  - **Pregled je dodatak, ne uslov.** Bez modela (ili kad model vrati nešto
    što nije sud) nacrt prolazi kao pre i to se zapisuje. Agent bez ključa ne
    sme da ostane bez posla, samo bez pregleda.
  - **Vraćanje traži razlog.** „Ne prihvatam" bez primedbe nije pregled nego
    prepreka, pa se takav sud odbacuje i nacrt prolazi.
  - **Šef ne prepisuje nacrt.** Ne piše svoju verziju i ne popravlja tekst;
    ili prihvata, ili vraća sa primedbom. Pisanje je izvršiočev posao.
"""

from __future__ import annotations

import dataclasses
import json
import re

from api import audit
from common import enums as E

#: Koliko nacrta ide u pregled. Duži se seče — šef čita početak, kao i čovek.
MAX_NACRT = 4000
MAX_PRIMEDBA = 600
MAX_NALOG = 600
MAX_PITANJE = 300

PREGLED_SYSTEM = (
    "Ti si šef sektora u firmi u kojoj poslove rade AI agenti. Tvoj izvršilac "
    "je napisao nacrt po nalogu koji ti je dao direktor. Tvoj posao NIJE da "
    "nacrt prepišeš nego da ga pregledaš pre nego što ga vratiš.\n"
    "Odgovaraš ISKLJUČIVO jednim JSON objektom, bez teksta oko njega:\n"
    '{"prihvatam": true, "primedba": "<kratko, ili prazno>", '
    '"trazi_vlasnika": false, "pitanje": "<prazno>"}\n'
    "Vrati nacrt (prihvatam: false) samo ako ima konkretnu grešku: ne "
    "odgovara nalogu, prazan je ili nedovršen, ili o firmi tvrdi nešto što "
    "ne piše u dosijeu (kupce, cene, usluge kojih nema). Drugačiji stil nije "
    "greška. Ako vraćaš nacrt, primedba je obavezna i kaže šta da se ispravi.\n"
    "Kad vraćaš nacrt, odluči još jedno: da li posao može da se ispravi bez "
    "vlasnika, ili zastaje dok vlasnik nešto ne odluči ili ne pojasni. Ako "
    "zastaje na vlasniku, stavi `trazi_vlasnika: true` i u `pitanje` napiši "
    "jedno kratko pitanje njemu (za koju stranu, koja odluka, koji podatak). "
    "Zanatsku grešku koju izvršilac može sam da ispravi (predugačko, loš "
    "naslov) NE guraj vlasniku — `trazi_vlasnika` ostaje false. "
    "Piši na srpskom."
)

_JSON = re.compile(r"\{.*\}", re.S)


@dataclasses.dataclass(frozen=True)
class Ishod:
    """Šefov sud o nacrtu. `presudio` je False kad suda nije bilo."""

    prihvacen: bool
    primedba: str = ""
    presudio: bool = False
    #: ADR-0111 — nacrt zastaje na vlasniku; `pitanje` je šta mu se pita.
    trazi_vlasnika: bool = False
    pitanje: str = ""


def _procitaj(tekst: str) -> dict | None:
    """Vadi sud iz modelovog odgovora; smeće vraća kao None.

    Lokalni šablon (`apps/llm_gateway/local.py`) ne ume JSON i to je u redu:
    tada suda nema, a nacrt ide dalje.
    """
    m = _JSON.search(tekst or "")
    if not m:
        return None
    try:
        sirovo = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(sirovo, dict) or "prihvatam" not in sirovo:
        return None
    return {"prihvatam": bool(sirovo.get("prihvatam")),
            "primedba": str(sirovo.get("primedba", "")).strip()[:MAX_PRIMEDBA],
            "trazi_vlasnika": bool(sirovo.get("trazi_vlasnika")),
            "pitanje": str(sirovo.get("pitanje", "")).strip()[:MAX_PITANJE]}


def oceni(sef, nalog: str, nacrt: str, *, run=None) -> Ishod:
    """Šefov pregled jednog nacrta. Nikad ne podiže grešku.

    Prazan nacrt se vraća bez modela: to je greška koju šef vidi i bez suda.
    """
    from apps.llm_gateway import gateway
    from apps.memory.context import _dosije_firme

    if not (nacrt or "").strip():
        return Ishod(False, "Nacrt je prazan.", True)

    # Dosije firme (ADR-0107) je jedini način da šef prepozna izmišljenog
    # kupca ili cenovnik kojeg nema.
    dosije = _dosije_firme()
    prompt = ((f"{dosije}\n\n---\n\n" if dosije else "")
              + f"Nalog:\n{(nalog or '')[:MAX_NALOG]}\n\nNacrt:\n{nacrt[:MAX_NACRT]}")
    try:
        gen = gateway.generate(E.LLMPurpose.EVALUATE, PREGLED_SYSTEM, prompt,
                               persona=sef, run=run,
                               brief={"tema": (nalog or "")[:200], "jezik": "sr-Latn"})
    except Exception as e:  # noqa: BLE001 — pregled ne sme da obori posao
        audit.record("content.pregled.bez_modela", persona=sef,
                     details={"razlog": f"{type(e).__name__}: {e}"[:200]})
        return Ishod(True, "", False)

    sud = _procitaj(gen.text)
    if sud is None:
        audit.record("content.pregled.bez_suda", persona=sef,
                     details={"odgovor": (gen.text or "")[:200]})
        return Ishod(True, "", False)
    if not sud["prihvatam"] and not sud["primedba"]:
        # Vraćanje bez razloga nije pregled nego prepreka.
        audit.record("content.pregled.bez_razloga", persona=sef, details={})
        return Ishod(True, "", False)
    # Traži vlasnika samo ako je nacrt stvarno vraćen i ima šta da se pita;
    # „treba vlasnik" bez pitanja je isto kao vraćanje bez razloga.
    trazi = (not sud["prihvatam"] and sud["trazi_vlasnika"]
             and bool(sud["pitanje"]))
    return Ishod(sud["prihvatam"], sud["primedba"], True,
                 trazi_vlasnika=trazi, pitanje=sud["pitanje"] if trazi else "")
