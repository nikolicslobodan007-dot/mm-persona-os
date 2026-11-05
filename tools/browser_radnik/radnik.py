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
      Otvara URL, izvlači MP4, snima ga u ./preuzeto/.
      --posalji: scp na server + ``sakupi --klip-fajl`` preko ssh.

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
    from playwright.sync_api import sync_playwright
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


def prijava() -> None:
    PROFIL.mkdir(exist_ok=True)
    print("Otvaram browser. Prijavi se na Facebook (i YouTube ako hoćeš).")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFIL), headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.facebook.com/")
        input("Kad se prijaviš, vrati se ovde i pritisni Enter...")
        ctx.close()
    print("Profil je sačuvan.")


def _povuci(page, video_url: str, cilj: Path) -> None:
    data_url = page.evaluate(_JS_FETCH, video_url)
    glava = data_url.split(",", 1)
    if len(glava) != 2:
        sys.exit("Neočekivan odgovor pri povlačenju fajla.")
    cilj.write_bytes(base64.b64decode(glava[1]))


def uzmi(url: str, maks: int, posalji: bool) -> None:
    if not PROFIL.exists():
        sys.exit("Nema sačuvane prijave. Prvo: python radnik.py prijava")
    PREUZETO.mkdir(exist_ok=True)
    ime = _ime_fajla(url)
    cilj = PREUZETO / ime
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFIL), headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"Otvaram: {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        html = page.evaluate("document.documentElement.innerHTML")
        video_url = _nadji_video_url(html)
        if not video_url:
            page.evaluate(_JS_PLAY)
            page.wait_for_timeout(3000)
            html = page.evaluate("document.documentElement.innerHTML")
            video_url = _nadji_video_url(html)
        if not video_url:
            ctx.close()
            sys.exit(
                "Nisam našao video (nema progressive_url). "
                "Proveri da si prijavljen i da URL vodi na snimak."
            )
        print("Našao video, povlačim fajl...")
        _povuci(page, video_url, cilj)
        ctx.close()
    mb = cilj.stat().st_size / 1048576
    print(f"Snimljeno: {cilj}  ({mb:.2f} MB)")
    if posalji:
        _posalji_i_sakupi(cilj, ime, maks)


def _posalji_i_sakupi(lokalni: Path, ime: str, maks: int) -> None:
    print(f"Šaljem na server: {SERVER}:{REMOTE_SECRETS}/{ime}")
    r1 = subprocess.run(["scp", str(lokalni), f"{SERVER}:{REMOTE_SECRETS}/{ime}"])
    if r1.returncode != 0:
        sys.exit("scp nije uspeo.")
    cmd = (
        f"cd {REMOTE_REPO} && docker compose exec -T web "
        f'python manage.py sakupi --klip-fajl "/app/secrets/{ime}" --maks {maks}'
    )
    print("Pokrećem sakupljač na serveru...")
    subprocess.run(["ssh", SERVER, cmd])


def main() -> None:
    ap = argparse.ArgumentParser(description="Browser radnik — video u sakupljač")
    sub = ap.add_subparsers(dest="komanda", required=True)
    sub.add_parser("prijava", help="jednokratna ručna prijava")
    u = sub.add_parser("uzmi", help="uzmi video sa URL-a")
    u.add_argument("url")
    u.add_argument("--maks", type=int, default=6)
    u.add_argument("--posalji", action="store_true", help="scp na server + sakupi")
    a = ap.parse_args()
    if a.komanda == "prijava":
        prijava()
    elif a.komanda == "uzmi":
        uzmi(a.url, a.maks, a.posalji)


if __name__ == "__main__":
    main()
