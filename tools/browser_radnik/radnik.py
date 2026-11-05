#!/usr/bin/env python3
"""Browser radnik — vadi video sa prijavljenog browsera i predaje ga sakupljaču.

Zašto postoji: skidanje sa servera (data-centar IP, bez prijave) FB/YT vide kao
bota. Prijavljeni browser sa rezidencijalne IP adrese to nije — on drži direktan
``progressive_url`` do MP4 fajla. Radnik radi tačno to, automatski.

Živi na PC-u (rezidencijalna IP, prijava). Kasnije se seli na farmu nepromenjen.

Upotreba:
  python radnik.py prijava
      Jednokratno otvara browser da se ručno prijaviš (FB/YT). Profil se pamti.

  python radnik.py uzmi <URL> [--maks N] [--posalji]
      Jedan snimak: izvuče MP4, snima u ./preuzeto/.
      --posalji: scp na server + ``sakupi --klip-fajl`` preko ssh.

  python radnik.py kolekcija <URL> [--najvise N] [--maks N] [--posalji]
      Sačuvana kolekcija / stranica: klikne prvi rils, prođe kroz scroller
      (strelica dole) i pokupi ID-eve, pa svaki obradi direktnim odlaskom na
      ``/reel/<id>`` (gde postoji progressive_url). --najvise ograničava broj.

Zavisnosti:
  pip install playwright
  playwright install chromium
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import Page, sync_playwright
except ImportError:
    sys.exit(
        "Playwright nije instaliran. Uradi:\n"
        "  pip install playwright\n"
        "  playwright install chromium"
    )

OVDE = Path(__file__).resolve().parent
PROFIL = OVDE / ".profil"
PREUZETO = OVDE / "preuzeto"

SERVER = os.environ.get("RADNIK_SERVER", "mm@49.12.77.226")
REMOTE_REPO = os.environ.get("RADNIK_REMOTE_REPO", "~/apps/mm-persona-os")
REMOTE_SECRETS = os.environ.get("RADNIK_REMOTE_SECRETS", "~/apps/mm-persona-os/secrets")

_KLJUCEVI = ("progressive_url", "browser_native_hd_url", "browser_native_sd_url")

_JS_FETCH = """
async (u) => {
  const r = await fetch(u);
  const blob = await r.blob();
  return await new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = rej;
    fr.readAsDataURL(blob);
  });
}
"""

_JS_PLAY = (
    "document.querySelectorAll('video')."
    "forEach(v => { v.muted = true; v.play().catch(() => {}); })"
)

def _ime_fajla(url: str) -> str:
    for obrazac in (r"/reel/(\d+)", r"/videos/(\d+)", r"[?&]v=([\w-]+)"):
        m = re.search(obrazac, url)
        if m:
            return f"klip-{m.group(1)}.mp4"
    return f"klip-{int(time.time())}.mp4"


def _nadji_video_url(html: str) -> str | None:
    for k in _KLJUCEVI:
        m = re.search(r'"' + k + r'":"(https:[^"]+?)"', html)
        if m:
            try:
                return json.loads('"' + m.group(1) + '"')
            except json.JSONDecodeError:
                return m.group(1).replace("\\/", "/")
    return None


def _proveri_prijavu() -> None:
    if not PROFIL.exists():
        sys.exit("Nema sacuvane prijave. Prvo: python radnik.py prijava")


def _otvori(p):
    ctx = p.chromium.launch_persistent_context(str(PROFIL), headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def _izvuci(page: Page, url: str) -> str | None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    video_url = _nadji_video_url(page.evaluate("document.documentElement.innerHTML"))
    if not video_url:
        page.evaluate(_JS_PLAY)
        page.wait_for_timeout(3000)
        video_url = _nadji_video_url(page.evaluate("document.documentElement.innerHTML"))
    return video_url


def _snimi(page: Page, video_url: str, cilj: Path) -> None:
    data_url = page.evaluate(_JS_FETCH, video_url)
    glava = data_url.split(",", 1)
    if len(glava) != 2:
        raise RuntimeError("Neocekivan odgovor pri povlacenju fajla.")
    cilj.write_bytes(base64.b64decode(glava[1]))


def _posalji_i_sakupi(lokalni: Path, ime: str, maks: int) -> None:
    print(f"  saljem na server: {ime}")
    poslato = subprocess.run(["scp", str(lokalni), f"{SERVER}:{REMOTE_SECRETS}/{ime}"])
    if poslato.returncode != 0:
        print("  scp nije uspeo, preskacem sakupljac.")
        return
    cmd = (
        f"cd {REMOTE_REPO} && docker compose exec -T web "
        f'python manage.py sakupi --klip-fajl "/app/secrets/{ime}" --maks {maks}'
    )
    subprocess.run(["ssh", SERVER, cmd])


def _jedan(page: Page, url: str, maks: int, posalji: bool) -> bool:
    ime = _ime_fajla(url)
    cilj = PREUZETO / ime
    if cilj.exists():
        print(f"  preskacem (vec imam): {ime}")
        return False
    video_url = _izvuci(page, url)
    if not video_url:
        print(f"  nema videa: {url}")
        return False
    _snimi(page, video_url, cilj)
    mb = cilj.stat().st_size / 1048576
    print(f"  snimljeno: {ime} ({mb:.2f} MB)")
    if posalji:
        _posalji_i_sakupi(cilj, ime, maks)
    return True


def _dijagnostika(page: Page) -> None:
    try:
        broj_a = page.evaluate("document.querySelectorAll('a[href]').length")
        tekst = page.evaluate("document.body ? document.body.innerText.length : 0")
        slika = OVDE / "dijagnostika.png"
        page.screenshot(path=str(slika))
        print(f"  URL: {page.url}")
        print(f"  naslov: {page.title()}")
        print(f"  <a> linkova: {broj_a}, duzina teksta: {tekst}")
        print(f"  slika sacuvana: {slika}")
    except Exception as e:
        print(f"  dijagnostika neuspela: {str(e)[:80]}")


def _graphql_idevi(page: Page, url: str, najvise: int) -> list[str]:
    tela: list[str] = []

    def _uhvati(resp) -> None:
        try:
            if "/api/graphql" in resp.url:
                tela.append(resp.text())
        except Exception:
            pass

    page.on("response", _uhvati)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    for _ in range(14):
        page.keyboard.press("End")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
    page.remove_listener("response", _uhvati)
    spojeno = "\n".join(tela)
    idevi: list[str] = []
    for m in re.finditer(r"\\?/reel\\?/(\d+)", spojeno):
        if m.group(1) not in idevi:
            idevi.append(m.group(1))
    print(f"  (graphql: {len(tela)} odgovora, {len(spojeno)} znakova, {len(idevi)} id-eva)")
    if not idevi:
        _dijagnostika(page)
    return idevi[:najvise]


def prijava() -> None:
    PROFIL.mkdir(exist_ok=True)
    print("Otvaram browser. Prijavi se na Facebook (i YouTube ako hoces).")
    with sync_playwright() as p:
        ctx, page = _otvori(p)
        page.goto("https://www.facebook.com/")
        input("Kad se prijavis, vrati se ovde i pritisni Enter...")
        ctx.close()
    print("Profil je sacuvan.")


def uzmi(url: str, maks: int, posalji: bool) -> None:
    _proveri_prijavu()
    PREUZETO.mkdir(exist_ok=True)
    print(f"Otvaram: {url}")
    with sync_playwright() as p:
        ctx, page = _otvori(p)
        try:
            ok = _jedan(page, url, maks, posalji)
        finally:
            ctx.close()
    if not ok:
        sys.exit("Nisam uspeo da uzmem video sa tog URL-a.")


def kolekcija(url: str, najvise: int, maks: int, posalji: bool) -> None:
    _proveri_prijavu()
    PREUZETO.mkdir(exist_ok=True)
    print(f"Nabrajam snimke sa: {url}")
    broj = 0
    with sync_playwright() as p:
        ctx, page = _otvori(p)
        try:
            idevi = _graphql_idevi(page, url, najvise)
            print(f"Nasao {len(idevi)} snimaka, obradjujem...")
            for i, rid in enumerate(idevi, 1):
                reel_url = f"https://www.facebook.com/reel/{rid}/"
                print(f"[{i}/{len(idevi)}] {reel_url}")
                try:
                    if _jedan(page, reel_url, maks, posalji):
                        broj += 1
                except Exception as greska:
                    print(f"  greska: {str(greska)[:80]}")
                page.wait_for_timeout(1500)
        finally:
            ctx.close()
    print(f"Gotovo: {broj} novih snimaka obradjeno.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Browser radnik — video u sakupljac")
    sub = ap.add_subparsers(dest="komanda", required=True)
    sub.add_parser("prijava", help="jednokratna rucna prijava")
    u = sub.add_parser("uzmi", help="jedan snimak sa URL-a")
    u.add_argument("url")
    u.add_argument("--maks", type=int, default=6)
    u.add_argument("--posalji", action="store_true", help="scp na server + sakupi")
    k = sub.add_parser("kolekcija", help="svi snimci sa kolekcije/stranice")
    k.add_argument("url")
    k.add_argument("--najvise", type=int, default=10)
    k.add_argument("--maks", type=int, default=6)
    k.add_argument("--posalji", action="store_true", help="scp na server + sakupi")
    a = ap.parse_args()
    if a.komanda == "prijava":
        prijava()
    elif a.komanda == "uzmi":
        uzmi(a.url, a.maks, a.posalji)
    elif a.komanda == "kolekcija":
        kolekcija(a.url, a.najvise, a.maks, a.posalji)


if __name__ == "__main__":
    main()
