"""Veritas — sud o izvoru: da li tekst izvora potvrđuje/oponira/ne pominje tvrdnju.

Jedan LLM poziv (Gateway, purpose EVALUATE) po izvoru: dobije TVRDNJU i TEKST
IZVORA, vrati stav. Veritas tako svrstava svaki izvor pre nego što verdikt motor
(`verdikt.oceni_tvrdnju`) izračuna pet osa. `--suvo` koristi lažni LLM.
"""

from __future__ import annotations

import json
import re

_CIRILICA = re.compile(r"[Ѐ-ӿ]")
_STAVOVI = ("potvrdjuje", "oponira", "ne_pominje")
_MAKS_IZVOR = 6000

_SISTEM = (
    "Ti si Veritas, proveravač. Dobijaš TVRDNJU i TEKST IZVORA. Oceni da li izvor "
    "potvrđuje, oponira ili uopšte ne pominje tvrdnju. Ne izmišljaš ništa van teksta. "
    "Vraćaš ISKLJUČIVO JSON objekat, na srpskom (latinica), bez reči van JSON-a."
)


def napravi_prompt(tvrdnja: str, tekst_izvora: str) -> str:
    t = (tekst_izvora or "")[:_MAKS_IZVOR]
    return (
        f"Tvrdnja: {tvrdnja}\n\n"
        "Na osnovu SAMO sledećeg teksta izvora, vrati objekat sa poljima:\n"
        '  "stav": "potvrdjuje" | "oponira" | "ne_pominje",\n'
        '  "obrazlozenje": jedna kratka rečenica zašto (srpski latinica).\n'
        'Ako izvor ne govori o tvrdnji, stav je "ne_pominje". '
        "Vrati ISKLJUČIVO taj JSON objekat.\n\n"
        "--- IZVOR ---\n"
        f"{t}\n"
        "--- KRAJ ---"
    )


def _parsiraj(sirovo: str) -> dict | None:
    s = sirovo.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i == -1 or j == -1:
        return None
    try:
        d = json.loads(s[i:j + 1])
    except json.JSONDecodeError:
        return None
    stav = str(d.get("stav", "")).strip().lower()
    if stav not in _STAVOVI:
        return None
    obr = str(d.get("obrazlozenje", "")).strip()
    if _CIRILICA.search(obr):
        obr = ""
    return {"stav": stav, "obrazlozenje": obr[:300]}


def _lazni_llm(prompt):
    return json.dumps(
        {"stav": "potvrdjuje", "obrazlozenje": "Izvor navodi isto što i tvrdnja."},
        ensure_ascii=False)


class GatewayLLM:
    """Pozvivo `llm(prompt)->str` kroz Gateway (EVALUATE); pamti poslednji Generation."""

    def __init__(self, *, persona=None, run=None):
        self.persona = persona
        self.run = run
        self.last = None

    def __call__(self, prompt: str) -> str:
        from apps.llm_gateway import gateway
        from common import enums as E
        g = gateway.generate(E.LLMPurpose.EVALUATE, _SISTEM, prompt,
                             persona=self.persona, run=self.run)
        self.last = g
        return g.text


def napravi_llm(*, persona=None, run=None) -> GatewayLLM:
    return GatewayLLM(persona=persona, run=run)


def oceni_izvor(tvrdnja: str, tekst_izvora: str, llm) -> dict | None:
    """Vrati {stav, obrazlozenje} ili None ako LLM nije vratio validan sud."""
    return _parsiraj(llm(napravi_prompt(tvrdnja, tekst_izvora)))
