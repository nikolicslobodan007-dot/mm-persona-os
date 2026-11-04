"""Sakupljanje ulaz — izvor (link / slika / klip) → tekst za destilaciju.

Isti ingest kao Veritas, samo usmeren ka vađenju VEŠTINA (ne tvrdnji):
  - web:   `uvoz_web` (SSRF/robots brane) → HTML → čist tekst (naslov + blokovi)
  - slika: `veritas.slika` (OCR, Tesseract, pretprocesiranje)
  - klip:  `veritas.klip` (yt-dlp + Groq Whisper ASR) — YouTube i direktni linkovi

Vraća {"tekst", "naslov", "izvor", "vrsta"}. `--suvo` svuda bez mreže i troška.
"""

from __future__ import annotations


class UlazGreska(Exception):
    pass


def _web(url: str, suvo: bool) -> dict:
    if suvo:
        return {"tekst": ("Da biste rešili problem, prvo napravite rezervnu kopiju, "
                          "pa primenite izmenu na malom uzorku i proverite rezultat."),
                "naslov": url, "izvor": url, "vrsta": "web"}
    from apps.libri import uvoz_web
    try:
        html = uvoz_web.preuzmi(url)
    except Exception as e:  # noqa: BLE001 — uvoz sme da padne (SSRF/robots/mreža)
        raise UlazGreska(f"web: {e}") from e
    (naslov, blokovi), _lang, _script = uvoz_web.naslov_i_blokovi(html)
    tekst = "\n".join(b["text"] for b in blokovi)
    return {"tekst": tekst, "naslov": naslov or url, "izvor": url, "vrsta": "web"}


def procitaj(vrsta: str, vrednost: str, *, suvo: bool = False) -> dict:
    """`vrsta` ∈ {web, slika, fajl, klip}; `vrednost` je URL ili putanja fajla."""
    if vrsta == "web":
        return _web(vrednost, suvo)
    if vrsta in ("slika", "fajl"):
        from apps.memory.veritas import slika
        r = slika.procitaj(vrednost, suvo=suvo, je_fajl=(vrsta == "fajl"))
        return {"tekst": r["tekst"], "naslov": vrednost, "izvor": vrednost, "vrsta": vrsta}
    if vrsta in ("klip", "klip_fajl"):
        from apps.memory.veritas import klip
        r = klip.transkribuj(vrednost, suvo=suvo, je_fajl=(vrsta == "klip_fajl"))
        return {"tekst": r["transkript"], "naslov": vrednost, "izvor": vrednost, "vrsta": vrsta}
    raise UlazGreska(f"nepoznata vrsta ulaza: {vrsta}")
