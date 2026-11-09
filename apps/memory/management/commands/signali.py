"""manage.py signali — GitHub Signals (githubsignals.io) kao izvor za sakupljač.

--lista:  pročita javni /export.csv, filtrira po zvezdicama, dedupe po repo_slug,
          NABRAJA kandidate (+ koju `sakupi` komandu bi pozvao). Bez troška.
--sakupi: za prvih --najvise NOVIH kandidata pozove `sakupi --url <repo>` i upiše
          veštine po repou u --izlaz-dir (preskače već obrađene). Troši LLM, pa
          traži --najvise N (N > 0) kao branu na trošak.

CSV kolone (11): published_at, provider, post_url, repo_slug, repo_url,
repo_stars, repo_keywords, caption, likes, plays, comments.

Primeri:
  python manage.py signali --lista --min-zvezdica 20 --maks 40
  python manage.py signali --sakupi --najvise 5 --min-zvezdica 50
  python manage.py signali --lista --csv-fajl /put/export.csv   # lokalni CSV (bez mreže)
"""

from __future__ import annotations

import csv
import io
import os
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

CSV_URL = "https://githubsignals.io/export.csv"
IZLAZ_DIR = "korpus/vestine/github-signals"


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


def _putanja(izlaz_dir: str, slug: str) -> str:
    """Izlazni JSON za repo: owner/repo → owner__repo.json."""
    return os.path.join(izlaz_dir, slug.replace("/", "__") + ".json")


def _za_obradu(kandidati: list[dict], izlaz_dir: str, najvise: int) -> list[tuple[dict, str]]:
    """Prvih `najvise` kandidata čiji izlazni fajl još ne postoji (dedup po fajlu)."""
    out: list[tuple[dict, str]] = []
    for r in kandidati:
        put = _putanja(izlaz_dir, r["slug"])
        if os.path.exists(put):
            continue
        out.append((r, put))
        if len(out) >= najvise:
            break
    return out


class Command(BaseCommand):
    help = "GitHub Signals izvor: nabroji (--lista) ili saberi (--sakupi) kandidate."

    def add_arguments(self, p):
        p.add_argument("--lista", action="store_true", help="Nabroji kandidate (bez troška).")
        p.add_argument("--sakupi", action="store_true",
                       help="Pozovi sakupi po kandidatu (troši LLM; traži --najvise).")
        p.add_argument("--csv-url", default=CSV_URL, help="URL CSV izvoza.")
        p.add_argument("--csv-fajl", help="Lokalni CSV umesto mreže (za test/offline).")
        p.add_argument("--min-zvezdica", type=int, default=20, help="Prag broja zvezdica.")
        p.add_argument("--maks", type=int, default=50,
                       help="--lista: najviše kandidata za ispis.")
        p.add_argument("--najvise", type=int, default=0,
                       help="--sakupi: koliko NOVIH repoa obraditi (obavezno > 0).")
        p.add_argument("--maks-vestina", type=int, default=8,
                       help="--sakupi: najviše veština po repou.")
        p.add_argument("--izlaz-dir", default=IZLAZ_DIR,
                       help="--sakupi: folder za rezultate po repou.")

    def handle(self, *args, **o):
        if o.get("sakupi"):
            return self._sakupi(o)
        if o.get("lista"):
            return self._lista(o)
        raise CommandError("Daj --lista ILI --sakupi.")

    def _lista(self, o):
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

    def _sakupi(self, o):
        najvise = o["najvise"]
        if najvise <= 0:
            raise CommandError("--sakupi traži --najvise N (N > 0) da ograniči trošak.")
        baza = getattr(settings, "BASE_DIR", os.getcwd())
        izlaz_dir = o["izlaz_dir"]
        izlaz_abs = izlaz_dir if os.path.isabs(izlaz_dir) else os.path.join(baza, izlaz_dir)
        os.makedirs(izlaz_abs, exist_ok=True)

        kandidati = _filtriraj(_parsiraj(self._ucitaj(o)), o["min_zvezdica"])
        za_obradu = _za_obradu(kandidati, izlaz_abs, najvise)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# sakupi: {len(za_obradu)} novih repoa "
            f"(od {len(kandidati)} kandidata ≥ {o['min_zvezdica']}★)"))
        if not za_obradu:
            self.stdout.write("Nema novih repoa (svi već obrađeni).")
            return

        obradjeno = 0
        for i, (r, put) in enumerate(za_obradu, 1):
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n[{i}/{len(za_obradu)}] {r['slug']} ({r['zvezdica']}★)"))
            try:
                call_command("sakupi", url=r["repo_url"], izlaz=put, maks=o["maks_vestina"])
                obradjeno += 1
            except Exception as e:  # noqa: BLE001 — jedan repo ne sme da sruši ceo batch
                self.stdout.write(self.style.ERROR(f"  greška: {str(e)[:120]}"))
            time.sleep(1)

        self.stdout.write(self.style.SUCCESS(
            f"\nObrađeno {obradjeno}/{len(za_obradu)} repoa → {izlaz_dir}/"))

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
