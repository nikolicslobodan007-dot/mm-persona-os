"""Koraci plana za sakupljanje — sažetak sa weba u delegaciji (ADR-0139).

Povezuje postojeću kapiju `ulaz.procitaj("web", url)` (uvoz_web → čist tekst;
za GitHub repo čita README) na lanac planova, da „pregledaj ovaj link i reci mi
šta je" zaista pročita stranicu i sažme je — a ne da napravi generičku objavu.
Modul se učitava preko `plans.HANDLER_MODULES`.
"""

from __future__ import annotations

from apps.orchestration import plans

MAKS_ULAZ = 12000


@plans.handler("web.sazetak")
def _sazetak(step: plans.PlanStep, state: dict) -> plans.Outcome:
    """URL iz koraka → pročitaj stranicu/repo → kratak tačan sažetak (iz teksta)."""
    from apps.content.service import _system_prompt
    from apps.llm_gateway import gateway
    from apps.memory.sakupljanje import ulaz
    from common import enums as E

    spec = step.input_json or {}
    url = (spec.get("url") or "").strip()
    if not url:
        return plans.Failed("Korak nema URL.")
    try:
        r = ulaz.procitaj("web", url)
    except Exception as e:  # noqa: BLE001 — mreža/robots/SSRF: korak staje čisto
        return plans.Failed(f"Nije učitano: {type(e).__name__}"[:200])
    tekst = (r.get("tekst") or "").strip()
    if not tekst:
        return plans.Failed("Stranica učitana, ali bez upotrebljivog teksta.")

    persona = step.plan.persona
    naslov = r.get("naslov", url)
    # ADR-0140 — handler odgovara na direktorov NALOG (ugao), ne fiksni sažetak.
    # Tako isti alat ume i čist sažetak i „kako bismo ovo mi koristili", zavisno
    # od pitanja. Činjenice ostaju iz teksta; zaključke koje nalog traži sme da
    # izvede. Bez naloga pada na podrazumevani sažetak.
    zadatak = (spec.get("tema") or "").strip() or (
        "Napiši kratak sažetak: šta je ovo, čemu služi, ključne stvari i ko "
        "stoji iza toga.")
    gen = gateway.generate(
        E.LLMPurpose.CONTENT_DRAFT, _system_prompt(persona),
        f"Pročitaj tekst sa {url} i uradi zadatak: \u201e{zadatak}\u201c.\n"
        f"Piši na srpskom (latinica), kratko i tačno. Činjenice o izvoru uzimaj "
        f"isključivo iz teksta — ne izmišljaj; ako neka činjenica ne piše, reci "
        f"da je u izvoru nema. Zaključke i procene koje zadatak traži slobodno "
        f"izvedi iz tih činjenica.\n\n"
        f"## tekst\n{tekst[:MAKS_ULAZ]}",
        persona=persona, run=step.plan.run, max_output=800,
        brief={"tema": naslov, "language": persona.primary_locale})
    return plans.Done({"sazetak": (gen.text or "")[:4000], "naslov": naslov,
                       "izvor": url})
