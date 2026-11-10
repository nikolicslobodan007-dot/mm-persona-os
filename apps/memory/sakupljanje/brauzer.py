"""Browser Task Gateway (skelet) — JS render preko Lightpanda pool-a, HTTP fallback.

Canon §12.1: engine je Playwright. Lightpanda nije drugi engine, nego CDP backend
na koji se Playwright kači (`connect_over_cdp`) umesto lokalnog Chromium-a — ista
Playwright mašina, lakši browser (farma, preko Tailscale-a). `connect_over_cdp`
traži SAMO playwright paket, ne lokalni Chromium binarni.

Engine izbor:
  - `LIGHTPANDA_CDP` podešen → Lightpanda pool (JS render) → engine "lightpanda";
  - pool nedostupan ILI prazno → fallback plain-HTTP (`uvoz_web.preuzmi`, BEZ JS)
    → engine "http". Na napregnutom serveru NE dižemo lokalni Chromium; težak JS
    render je na farmi, a fallback je lagan.

SSRF/robots: CDP put proverava sam (Playwright ne); HTTP fallback ide kroz
`uvoz_web.preuzmi` koji nosi svoje SSRF/robots/cap brane.

Env: `LIGHTPANDA_CDP = ws://<tailscale-ip>:9222` (prazno → odmah HTTP fallback).

NAPOMENA: skelet za Lightpanda pilot — JOŠ nije uvezan u `ulaz._web`. Wiring posle
merenja na farmi. Vidi `claude/nacrt-09-11-lightpanda-browser-pool-farma.md`.
"""

from __future__ import annotations

import os


class BrauzerGreska(Exception):
    pass


def cdp_iz_okruzenja() -> str:
    """CDP endpoint Lightpanda pool-a iz env-a; prazno = odmah HTTP fallback."""
    return os.environ.get("LIGHTPANDA_CDP", "").strip()


def _render_cdp(url: str, cdp: str, ua: str, timeout: float) -> dict:
    """JS render preko Lightpanda pool-a (Playwright `connect_over_cdp`). Diže na grešku."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp)
        try:
            ctx = browser.new_context(
                user_agent=ua, locale="sr-RS",
                extra_http_headers={"Accept-Language": "sr-RS,sr;q=0.9,en;q=0.7"})
            page = ctx.new_page()
            page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
            html, naslov = page.content(), page.title()
        finally:
            browser.close()
    return {"html": html, "naslov": naslov}


def render(url: str, *, suvo: bool = False, timeout: float = 20.0) -> dict:
    """Stranica → {tekst(HTML), naslov, izvor, engine}. Lightpanda pool → HTTP fallback.

    `engine`: 'lightpanda' (JS, pool) | 'http' (plain, bez JS) | 'suvo'.
    """
    if suvo:
        return {"tekst": "<html>Suvi render (bez mreže).</html>", "naslov": url,
                "izvor": url, "engine": "suvo"}

    from apps.libri import uvoz_web

    cdp = cdp_iz_okruzenja()
    if cdp:
        uvoz_web.proveri_bezbedan(url)
        ua = uvoz_web._ua()
        if not uvoz_web._robots_dozvoljava(url, ua):
            raise BrauzerGreska("robots.txt zabranjuje čitanje ovog URL-a.")
        try:
            r = _render_cdp(url, cdp, ua, timeout)
            return {"tekst": r["html"], "naslov": r["naslov"] or url,
                    "izvor": url, "engine": "lightpanda"}
        except Exception:  # noqa: BLE001 — pool nedostupan → degradiraj na HTTP
            pass

    # Fallback: plain HTTP (preuzmi nosi SSRF/robots/cap brane). Bez JS.
    try:
        html = uvoz_web.preuzmi(url)
    except Exception as e:  # noqa: BLE001 — mreža/robots/cap
        raise BrauzerGreska(f"render nije uspeo (HTTP): {e}") from e
    return {"tekst": html, "naslov": url, "izvor": url, "engine": "http"}
