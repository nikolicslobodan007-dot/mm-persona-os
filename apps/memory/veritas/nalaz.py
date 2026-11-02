"""Veritas — ekstraktor nalaza: tekst → strukturirane tvrdnje (tri sloja).

Za svaku tvrdnju vraća tri sloja (nacrt „Veritas — čitanje između redova"):
  1. doslovna   — šta je bukvalno rečeno,
  2. implicirana — šta objava hoće da poverujem (ili prazno),
  3. tehnika    — kojim sredstvom vodi ka zaključku (taksonomija ili „nema").
Uz to: `za_proveru` (šta bi proveravač morao da potvrdi) i `pouzdanost`
(koliko je ekstraktor siguran da je TAČNO PROČITAO tvrdnju/tehniku — NE da je
tvrdnja istinita; istinu utvrđuje provera, slice 2).

DISCIPLINA (ADR-nacrt): Veritas NE tvrdi da je nešto tačno/lažno i NE pripisuje
nameru. Imenuje tehniku samo kad je jasna iz teksta; inače „nema". „Uokvirivanje
sugeriše X" je analiza; „svesno te lažu" je optužba koju ekstraktor ne izriče.

Pravi rad zove F7 Gateway (purpose EXTRACT, ADR-0086); `--suvo` koristi lažni LLM.
"""

from __future__ import annotations

import json
import re

_CIRILICA = re.compile(r"[Ѐ-ӿ]")
_MAKS_DUZINA = 400

_TEHNIKE = (
    "uokvirivanje", "precutkivanje", "podmetnuto susedstvo", "vadjenje iz konteksta",
    "lazna ekvivalencija", "insinuacija", "prebacivanje tereta", "nema",
)

_SISTEM = (
    "Ti si Veritas, precizan analitičar tvrdnji u srpskoj redakciji. Iz datog "
    "teksta izdvajaš tvrdnje i način na koji su uokvirene. NE sudiš da li su "
    "istinite (to radi provera), i NE pripisuješ nameru. Vraćaš ISKLJUČIVO "
    "traženi JSON niz, na srpskom (latinica), bez ijedne reči van JSON-a."
)


def napravi_prompt(tekst: str, maks: int) -> str:
    teh = ", ".join(_TEHNIKE)
    return (
        "Iz sledećeg teksta izdvoj najviše "
        f"{maks} zasebnih tvrdnji. Za svaku vrati objekat sa poljima:\n"
        '  "doslovna": šta je bukvalno rečeno (kratko, našim rečima),\n'
        '  "implicirana": šta objava hoće da se poveruje — ili "" ako nema podteksta,\n'
        f'  "tehnika": jedna od [{teh}] ("nema" ako nema uočljivog uokvirivanja),\n'
        '  "za_proveru": šta bi proveravač morao da potvrdi da bi se tvrdnja ocenila,\n'
        '  "pouzdanost": broj 0-1 koliko si siguran da si TAČNO PROČITAO tvrdnju '
        "(ne da je istinita).\n"
        "Pravila: sve na srpskom latinicom; bez ćirilice; ne izmišljaj nameru; "
        "tehniku imenuj samo kad je jasna iz teksta; ne tvrdi istinitost. "
        "Vrati ISKLJUČIVO JSON niz tih objekata, ništa drugo.\n\n"
        "--- TEKST ---\n"
        f"{tekst}\n"
        "--- KRAJ ---"
    )


def _parsiraj(sirovo: str, maks: int) -> list[dict]:
    s = sirovo.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    i, j = s.find("["), s.rfind("]")
    if i == -1 or j == -1:
        return []
    try:
        podaci = json.loads(s[i:j + 1])
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for v in podaci:
        if not isinstance(v, dict):
            continue
        doslovna = str(v.get("doslovna", "")).strip()
        if not doslovna or len(doslovna) > _MAKS_DUZINA:
            continue
        implicirana = str(v.get("implicirana", "")).strip()
        za_proveru = str(v.get("za_proveru", "")).strip()
        tehnika = str(v.get("tehnika", "nema")).strip().lower()
        if tehnika not in _TEHNIKE:
            tehnika = "nema"
        polja = (doslovna, implicirana, za_proveru)
        if any(_CIRILICA.search(x) for x in polja if x):
            continue
        if any(len(x) > _MAKS_DUZINA for x in polja):
            continue
        try:
            pouzdanost = float(v.get("pouzdanost", 0.7))
        except (TypeError, ValueError):
            pouzdanost = 0.7
        pouzdanost = round(min(max(pouzdanost, 0.0), 1.0), 2)
        out.append({"doslovna": doslovna, "implicirana": implicirana,
                    "tehnika": tehnika, "za_proveru": za_proveru,
                    "pouzdanost": pouzdanost})
        if len(out) >= maks:
            break
    return out


def _lazni_llm(prompt):
    """Suvi režim: deterministički nalaz, nula poziva ka Gateway-u."""
    return json.dumps([{
        "doslovna": "U tekstu se iznosi jedna konkretna tvrdnja.",
        "implicirana": "Tekst sugeriše širi zaključak koji nije izrečen.",
        "tehnika": "uokvirivanje",
        "za_proveru": "Uporediti tvrdnju sa nezavisnim izvorom pre ocene.",
        "pouzdanost": 0.6,
    }], ensure_ascii=False)


class GatewayLLM:
    """Pozvivo `llm(prompt)->str` kroz F7 Gateway; pamti poslednji Generation."""

    def __init__(self, *, persona=None, run=None):
        self.persona = persona
        self.run = run
        self.last = None

    def __call__(self, prompt: str) -> str:
        from apps.llm_gateway import gateway
        from common import enums as E
        g = gateway.generate(E.LLMPurpose.EXTRACT, _SISTEM, prompt,
                             persona=self.persona, run=self.run)
        self.last = g
        return g.text


def napravi_llm(*, persona=None, run=None) -> GatewayLLM:
    return GatewayLLM(persona=persona, run=run)


def izvuci_nalaze(tekst: str, llm, maks: int = 6) -> list[dict]:
    """Pozovi `llm` nad promptom i vrati listu nalaza (tri sloja po tvrdnji)."""
    sirovo = llm(napravi_prompt(tekst, maks))
    return _parsiraj(sirovo, maks)
