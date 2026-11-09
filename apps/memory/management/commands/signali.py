"""manage.py signali — GitHub Signals (githubsignals.io) kao izvor za sakupljač.

Čita javni CSV izvoz arhive (/export.csv), filtrira po broju zvezdica, izbaci
duplikate po repo_slug i NABRAJA kandidate — za svaki ispiše koju bi `sakupi`
komandu pozvao (repo → `--url`, YouTube video → `--klip-url`). NE destiluje
ništa (bez troška/LLM). Sam harvest (poziv `sakupi`) je zaseban, kasniji slice.

CSV kolone (11): published_at, provider, post_url, repo_slug, repo_url,
repo_stars, repo_keywords, caption, likes, plays, comments.

Primeri:
  python manage.py signali --lista                       # top kandidati sa /export.csv
  python manage.py signali --lista --min-zvezdica 50 --maks 30
  python manage.py signali --lista --csv-fajl /put/export.csv   # lokalni CSV (bez mreže)
"""

from __future__ import annotations

import csv
import io
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

CSV_URL = "https://githubsignals.io/export.csv"


def _ceo_broj(s: str) -> int:
    try:
        return int((s or "").strip() or 0)
    except ValueError:
        return 0


def _parsiraj(csv_tekst: str) -> list[dict]:
    """CSV tekst → lista normalizovanih redova (samo bitne kolone)."""
    redovi: list[dict] = []
    for r in csv.DictReader(io.StringIO(csv_tekst)):
        slug = (r.get("repo_slug") or "").strip()
        repo = (r.get("repo_url") or "").strip()
        if not slug or not repo:
            continue
        redovi.append({
            "slug": slug,
            "repo_url": repo,
            "zvezdica": _ceo_broj(r.get("repo_stars")),
            "kljucne_reci": (r.get("repo_keywords") or "").strip(),
            "provajder": (r.get("provider") or "").strip().lower(),
            "post_url": (r.get("post_url") or "").strip(),
        })
    return redovi


def _filtriraj(redovi: list[dict], min_zvezdica: int) -> list[dict]:
    """Prag zvezdica + dedup po slug-u (prvi pobedi) + sort opadajuće po zvezdicama."""
    vidjeno: set[str] = set()
    izlaz: list[dict] = []
    for r in sorted(redovi, key=lambda x: x["zvezdica"], reverse=True):
        if r["zvezdica"] < min_zvezdica or r["slug"] in vidjeno:
            continue
        vidjeno.add(r["slug"])
        izlaz.append(r)
    return izlaz


def _komande(r: dict) -> list[str]:
    """Koje bi `sakupi` komande ovaj unos pozvao (repo uvek; YouTube video ako ga ima)."""
    kom = [f'manage.py sakupi --url "{r["repo_url"]}"']
    if r["provajder"] == "youtube" and r["post_url"]:
        kom.append(f'manage.py sakupi --klip-url "{r["post_url"]}"')
    return kom


class Command(BaseCommand):
    help = "GitHub Signals izvor: nabroji kandidate iz /export.csv (bez destilacije)."

    def add_arguments(self, p):
        p.add_argument("--lista", action="store_true",
                       help="Nabroji kandidate (jedini režim za sada).")
        p.add_argument("--csv-url", default=CSV_URL, help="URL CSV izvoza.")
        p.add_argument("--csv-fajl", help="Lokalni CSV umesto mreže (za test/offline).")
        p.add_argument("--min-zvezdica", type=int, default=20, help="Prag broja zvezdica.")
        p.add_argument("--maks", type=int, default=50, help="Najviše kandidata za ispis.")

    def handle(self, *args, **o):
        if not o.get("lista"):
            raise CommandError("Za sada postoji samo režim --lista.")

        svi = _parsiraj(self._ucitaj(o))
        kandidati = _filtriraj(svi, o["min_zvezdica"])

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# GitHub Signals: {len(svi)} redova, "
            f"{len(kandidati)} kandidata (≥ {o['min_zvezdica']} zvezdica)"))

        jutjub = 0
        for r in kandidati[:o["maks"]]:
            reci = f"  [{r['kljucne_reci']}]" if r["kljucne_reci"] else ""
            self.stdout.write(f"\n- {r['slug']}  ({r['zvezdica']}★){reci}")
            for k in _komande(r):
                self.stdout.write(f"    {k}")
            if r["provajder"] == "youtube" and r["post_url"]:
                jutjub += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nIspisano {min(len(kandidati), o['maks'])} od {len(kandidati)} "
            f"kandidata; {jutjub} sa YouTube videom (ide i kroz --klip-url)."))

    def _ucitaj(self, o) -> str:
        if o.get("csv_fajl"):
            baza = getattr(settings, "BASE_DIR", os.getcwd())
            put = o["csv_fajl"]
            put = put if os.path.isabs(put) else os.path.join(baza, put)
            if not os.path.isfile(put):
                raise CommandError(f"Nema CSV fajla: {put}")
            with open(put, encoding="utf-8") as fh:
                return fh.read()
        from apps.libri import uvoz_web
        try:
            return uvoz_web.preuzmi(o["csv_url"])
        except Exception as e:  # noqa: BLE001 — mreža/robots sme da padne, javi jasno
            raise CommandError(f"CSV preuzimanje nije uspelo: {e}") from e
