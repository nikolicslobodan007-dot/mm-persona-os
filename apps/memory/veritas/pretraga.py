"""Veritas — autonomna pretraga izvora (Brave Search API, slice 2b).

Za datu tvrdnju vraća listu kandidata-URL-ova koje verdikt tok (uvoz_web → sud →
verdikt) zatim proverava. Ne dohvata sadržaj ovde — samo imena izvora; bezbednosne
brane (SSRF/robots) rade u `uvoz_web` pri dohvatu. Ključ: `BRAVE_SEARCH_API_KEY`
(env, u `.env` na serveru). `--suvo` koristi lažni pretraživač (nula poziva/para).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def _kljuc() -> str:
    from django.conf import settings
    return (os.environ.get("BRAVE_SEARCH_API_KEY")
            or getattr(settings, "BRAVE_SEARCH_API_KEY", "") or "")


def _parsiraj(data: dict, maks: int) -> list[dict]:
    rez = ((data or {}).get("web") or {}).get("results") or []
    out: list[dict] = []
    videno: set[str] = set()
    for r in rez:
        url = str(r.get("url", "")).strip()
        if not url.startswith("http") or url in videno:
            continue
        videno.add(url)
        out.append({"url": url, "naslov": str(r.get("title", ""))[:160]})
        if len(out) >= maks:
            break
    return out


def pretrazi(upit: str, maks: int = 5, *, kljuc: str | None = None) -> list[dict]:
    """Vrati [{url, naslov}] iz Brave Search-a. Diže grešku ako nema ključa."""
    kljuc = kljuc or _kljuc()
    if not kljuc:
        raise RuntimeError("Nema BRAVE_SEARCH_API_KEY (dodaj u .env na serveru).")
    q = urllib.parse.urlencode({"q": upit, "count": max(1, min(maks, 20)),
                                "search_lang": "sr", "country": "RS"})
    req = urllib.request.Request(
        f"{_ENDPOINT}?{q}",
        headers={"Accept": "application/json", "X-Subscription-Token": kljuc,
                 "User-Agent": "VeritasBot/1.0 (Persona OS)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return _parsiraj(data, maks)


def _lazni(upit: str, maks: int = 5, **_) -> list[dict]:
    """Suvi režim: deterministički kandidati, bez poziva ka Brave-u."""
    return [{"url": f"https://primer{i}.rs/clanak-o-temi", "naslov": f"Primer izvora {i}"}
            for i in range(1, min(maks, 3) + 1)]
