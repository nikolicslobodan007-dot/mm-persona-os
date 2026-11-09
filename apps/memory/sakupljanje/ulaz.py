"""Sakupljanje ulaz — izvor (link / slika / klip) → tekst za destilaciju.

Isti ingest kao Veritas, samo usmeren ka vađenju VEŠTINA (ne tvrdnji):
  - web:   `uvoz_web` (SSRF/robots brane) → HTML → čist tekst (naslov + blokovi).
           GitHub repo koren se čita kao PUN README (raw), ne kao HTML landing
           (landing daje mrvice; README je sadržaj). Fallback na HTML ako nema.
  - slika: `veritas.slika` (OCR, Tesseract, pretprocesiranje)
  - klip:  `veritas.klip` (yt-dlp + Groq Whisper ASR) — YouTube i direktni linkovi

Vraća {"tekst", "naslov", "izvor", "vrsta"}. `--suvo` svuda bez mreže i troška.
"""

from __future__ import annotations

from urllib.parse import urlsplit


class UlazGreska(Exception):
    pass


# github.com putanje koje NISU repo koren (ne čitaj README za njih).
_GH_NE_REPO = frozenset((
    "features", "about", "pricing", "marketplace", "sponsors", "settings",
    "orgs", "topics", "search", "collections", "trending", "apps",
    "notifications", "explore", "login", "join", "new", "organizations",
))


def _github_repo(url: str) -> tuple[str, str] | None:
    """(owner, repo) ako je `url` github.com repo koren, inače None."""
    d = urlsplit(url)
    if d.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    delovi = [p for p in d.path.split("/") if p]
    if len(delovi) < 2 or delovi[0].lower() in _GH_NE_REPO:
        return None
    owner, repo = delovi[0], delovi[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _github_readme(owner: str, repo: str) -> str:
    """Pun README sa raw.githubusercontent.com (proba glavne grane/imena). '' ako ne nađe."""
    from apps.libri import uvoz_web
    kandidati = (
        ("HEAD", "README.md"), ("main", "README.md"), ("master", "README.md"),
        ("HEAD", "readme.md"), ("HEAD", "README.rst"),
    )
    for ref, ime in kandidati:
        sirovi = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{ime}"
        try:
            tekst = uvoz_web.preuzmi(sirovi).strip()
        except Exception:  # noqa: BLE001 — probaj sledeći kandidat
            continue
        if len(tekst) > 200:
            return tekst
    return ""


def _web(url: str, suvo: bool) -> dict:
    if suvo:
        return {"tekst": ("Da biste rešili problem, prvo napravite rezervnu kopiju, "
                          "pa primenite izmenu na malom uzorku i proverite rezultat."),
                "naslov": url, "izvor": url, "vrsta": "web"}
    # GitHub repo: pun README (raw) je bogatiji od HTML landinga.
    gh = _github_repo(url)
    if gh:
        readme = _github_readme(*gh)
        if readme:
            return {"tekst": readme, "naslov": f"{gh[0]}/{gh[1]} (README)",
                    "izvor": url, "vrsta": "web"}
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
