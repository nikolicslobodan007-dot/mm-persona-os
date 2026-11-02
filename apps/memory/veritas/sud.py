"""Veritas — sud o izvoru: da li tekst izvora potvrđuje/oponira/ne pominje tvrdnju.

Jedan LLM poziv (Gateway, purpose EVALUATE) po izvoru. Ključna finesa (02.11):
razdvaja da li je nešto IZREČENO/dogodilo se (činjenica) od TUMAČENJA (značenja).
„Izvučeno iz konteksta" odbrana NE poriče da je izrečeno — zato poseban stav
`potvrdjuje_sporno_tumacenje`. `--suvo` koristi lažni LLM.
"""

from __future__ import annotations

import json
import re

_CIRILICA = re.compile(r"[Ѐ-ӿ]")
_STAVOVI = ("potvrdjuje", "potvrdjuje_sporno_tumacenje", "oponira", "ne_pominje")
_MAKS_IZVOR = 6000

_SISTEM = (
    "Ti si Veritas, proveravač. Dobijaš TVRDNJU i TEKST IZVORA i oceniš stav izvora. "
    "Razlikuj DVE stvari: (1) da li je nešto IZREČENO ili se DOGODILO (činjenica), i "
    "(2) TUMAČENJE/značenje toga. Ne izmišljaš ništa van teksta. Vraćaš ISKLJUČIVO "
    "JSON objekat, na srpskom (latinica), bez ijedne reči van JSON-a."
)


def napravi_prompt(tvrdnja: str, tekst_izvora: str) -> str:
    t = (tekst_izvora or "")[:_MAKS_IZVOR]
    return (
        f"Tvrdnja: {tvrdnja}\n\n"
        "Na osnovu SAMO sledećeg teksta izvora, vrati objekat sa poljima:\n"
        '  "stav": jedno od:\n'
        '     "potvrdjuje" — izvor potvrđuje da je izrečeno/da se dogodilo;\n'
        '     "potvrdjuje_sporno_tumacenje" — potvrđuje da je IZREČENO, ali SPORI '
        'tumačenje/značenje (npr. „izvučeno iz konteksta", „pogrešno protumačeno");\n'
        '     "oponira" — izvor PORIČE da je izrečeno/da se dogodilo (tvrdi da nije '
        "rečeno, da je izmišljeno ili montaža);\n"
        '     "ne_pominje" — izvor ne govori o tome;\n'
        '  "obrazlozenje": jedna kratka rečenica zašto (srpski latinica).\n'
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
