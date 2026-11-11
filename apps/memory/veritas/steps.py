"""Koraci plana za Veritas klip — transkripcija videa u delegaciji (ADR-0136).

Povezuje postojeću kapiju `klip.transkribuj(url)` (yt-dlp → ffmpeg → Gateway
TRANSCRIBE) na lanac planova, da „prepiši video" zaista ode na ASR, a ne na
generički `content.draft`. Modul se učitava preko `plans.HANDLER_MODULES`.
"""

from __future__ import annotations

from apps.orchestration import plans


@plans.handler("klip.prepis")
def _prepis(step: plans.PlanStep, state: dict) -> plans.Outcome:
    """URL videa iz koraka → prepis (ASR). Izvor stoji uz prepis."""
    from apps.memory.veritas import klip

    spec = step.input_json or {}
    url = (spec.get("url") or "").strip()
    if not url:
        return plans.Failed("Korak nema URL videa.")
    try:
        rez = klip.transkribuj(url, persona=step.plan.persona)
    except klip.KlipGreska as e:
        return plans.Failed(f"Video nije obrađen: {e}"[:300])
    except Exception as e:  # noqa: BLE001 — yt-dlp/mreža pala: korak staje čisto
        return plans.Failed(f"Video nije skinut/obrađen: {type(e).__name__}"[:300])
    transkript = (rez.get("transkript") or "").strip()
    if not transkript:
        return plans.Failed("Video obrađen, ali bez prepisa (nema govora?).")
    return plans.Done({
        "transkript": transkript[:4000],
        "izvor": rez.get("izvor_url", url),
        "asset": rez.get("asset_id", ""),
        "tema": spec.get("tema", ""),
    })
