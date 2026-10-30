"""Adapter: wk_destilacija `llm(prompt)->str` → F7 LLM Gateway (purpose EXTRACT).

Isti kalup kao Libri ekstrakt (`apps/libri/ekstrakt.py::_pozovi`):
`gateway.generate(E.LLMPurpose.EXTRACT, _SISTEM, prompt, persona=...)`.

Time `sakupljanje` više ne zavisi od spoljnog LLM-a „u ruci" — agent sam, kroz
Gateway, destiluje veštinu. Izbor rute, dozvola (`_external_allowed`,
`data_training_allowed`), cena i zapis ostaju u Gateway-u (ADR-0086); ovde je
samo šav koji wk-sloju daje `llm(prompt)->str`.
"""

from __future__ import annotations

# Prompt iz wk_destilacija.napravi_prompt već nosi puna uputstva i traži „isključivo
# JSON niz". Sistemska poruka samo učvršćuje format.
_SISTEM = (
    "Ti si precizan bibliotekar veština u srpskoj AI korporaciji. "
    "Prati uputstvo iz poruke doslovno i vrati ISKLJUČIVO traženi JSON niz, "
    "na srpskom (latinica sa dijakritikom), bez ijedne reči van JSON-a."
)


class GatewayLLM:
    """Pozvivo (callable) koje wk_destilacija koristi kao `llm`. Pamti poslednji
    `Generation` radi dijagnostike (provajder, model, tokeni, cena)."""

    def __init__(self, sistem: str = _SISTEM, *, persona=None, run=None):
        self.sistem = sistem
        self.persona = persona
        self.run = run
        self.last = None  # poslednji Generation

    def __call__(self, prompt: str) -> str:
        from apps.llm_gateway import gateway
        from common import enums as E
        g = gateway.generate(E.LLMPurpose.EXTRACT, self.sistem, prompt,
                             persona=self.persona, run=self.run)
        self.last = g
        return g.text


def napravi_llm(*, persona=None, run=None) -> GatewayLLM:
    """Vrati Gateway-om vođen `llm` za wk_destilacija/wk_sakupljanje."""
    return GatewayLLM(persona=persona, run=run)
