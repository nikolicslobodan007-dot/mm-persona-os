"""Browser Task Gateway (skelet) — render stranice (JS) preko Playwright-a.

Canon §12.1: engine je Playwright i SAMO Playwright. Lightpanda se NE uvodi kao
drugi engine, nego kao CDP backend na koji se Playwright kači
(`connect_over_cdp`) umesto da lokalno diže Chromium — ista Playwright mašina,
samo lakši browser (na farmi, preko Tailscale-a). Ako CDP nije podešen ili
padne → fallback na lokalni Chromium (`launch`), pa render NE zavisi od farme.

Env: `LIGHTPANDA_CDP = ws://<tailscale-ip>:9222` (prazno → uvek lokalni Chromium).

SSRF/robots brane se dele sa `apps.libri.uvoz_web` (ista pravila kao plain HTTP
ingest). Vraća sirov HTML (render); parsiranje u čist tekst radi pozivalac
(`uvoz_web.naslov_i_blokovi`).

NAPOMENA: skelet za Lightpanda pilot — JOŠ nije uvezan u `ulaz._web` ni u runtime
`transport`. Wiring i konačno mesto (verovatno runtime F6) posle merenja na farmi.
Vidi `claude/nacrt-09-11-lightpanda-browser-pool-farma.md`.
"""

from __future__ import annotations

import os


class BrauzerGreska(Exception):
    pass


def cdp_iz_okruzenja() -> str:
    """CDP endpoint Lightpanda pool-a iz env-a; prazno = lokalni Chromium."""
    return os.environ.get("LIGHTPANDA_CDP", "").strip()


def _otvori(p, cdp: str):
    """Playwright browser: CDP (Lightpanda pool) ako je `cdp` zadat, inače lokalni Chromium."""
    if cdp:
        return p.chromium.connect_over_cdp(cdp)
    return p.chromium.launch(headless=True)


def _render_jednom(url: str, cdp: str, ua: str, timeout: float) -> dict:
    """Jedan pokušaj rendera datim engine-om (CDP ili lokalni). Diže izuzetak na grešku."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _otvori(p, cdp)
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
    """Render stranice → {tekst(sirov HTML), naslov, izvor, engine}. SSRF/robots brane.

    Pokušaj Lightpanda pool (CDP) ako je `LIGHTPANDA_CDP` podešen; na grešku
    fallback lokalni Chromium. `engine` kaže šta je stvarno upotrebljeno
    ('lightpanda' | 'chromium' | 'suvo').
    """
    if suvo:
        return {"tekst": "<html>Suvi render (bez mreže).</html>", "naslov": url,
                "izvor": url, "engine": "suvo"}

    from apps.libri import uvoz_web
    uvoz_web.proveri_bezbedan(url)
    ua = uvoz_web._ua()
    if not uvoz_web._robots_dozvoljava(url, ua):
        raise BrauzerGreska("robots.txt zabranjuje čitanje ovog URL-a.")

    cdp = cdp_iz_okruzenja()
    pokusaji = ([("lightpanda", cdp)] if cdp else []) + [("chromium", "")]
    greske: list[str] = []
    for engine, c in pokusaji:
        try:
            r = _render_jednom(url, c, ua, timeout)
        except Exception as e:  # noqa: BLE001 — probaj sledeći engine (fallback)
            greske.append(f"{engine}: {str(e)[:120]}")
            continue
        return {"tekst": r["html"], "naslov": r["naslov"] or url,
                "izvor": url, "engine": engine}
    raise BrauzerGreska("render nije uspeo: " + " | ".join(greske))
