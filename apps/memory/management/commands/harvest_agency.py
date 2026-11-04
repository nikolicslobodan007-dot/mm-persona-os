"""manage.py harvest_agency — destiluje agency-agents .md definicije u srpske veštine.

Čita .md definicije specijalista (npr. korpus/izvori/agency-agents-security/*.md),
svaku provuče kroz destilator (F7 Gateway, purpose EXTRACT) i izvuče do N veština
u našem formatu {ime, koraci, napomene, pouzdanost} — na srpskom (latinica), NAŠ
opis postupka, ne prepis. Rezultat upisuje u korpus/vestine/<izlaz>.json i ispisuje
cenu (tokeni, €¢) po fajlu i zbir.

Jezgro destilacije živi u `apps.memory.sakupljanje.destilator` (deli ga sakupljač
`sakupi`); ovde ostaje čitanje .md (frontmatter) i upis u korpus.

Primeri:
  python manage.py harvest_agency --divizija security
  python manage.py harvest_agency --sve                 # sve vendorovane divizije
  python manage.py harvest_agency --izvor-dir korpus/izvori/agency-agents-security \
      --izlaz korpus/vestine/agency-agents-security.json --maks-po-fajlu 4
  python manage.py harvest_agency --divizija security --suvo   # bez troška (lažni LLM)
"""

from __future__ import annotations

import glob
import json
import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.memory.sakupljanje import destilator


def _sk_frontmatter(tekst: str) -> tuple[str, str, str]:
    """Vrati (name, description, telo_bez_frontmatter) iz .md sa YAML zaglavljem."""
    name, desc = "", ""
    telo = tekst
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", tekst, re.S)
    if m:
        glava, telo = m.group(1), m.group(2)
        for red in glava.splitlines():
            if red.lower().startswith("name:"):
                name = red.split(":", 1)[1].strip().strip('"')
            elif red.lower().startswith("description:"):
                desc = red.split(":", 1)[1].strip().strip('"')
    return name, desc, telo.strip()


class Command(BaseCommand):
    help = "Destiluje agency-agents .md definicije u srpske veštine (kroz Gateway)."

    def add_arguments(self, p):
        p.add_argument("--divizija", help="naziv divizije (npr. security) — izvor i izlaz po njoj")
        p.add_argument("--izvor-dir", help="direktorijum sa .md definicijama")
        p.add_argument("--izlaz", help="putanja izlaznog .json (korpus/vestine/...)")
        p.add_argument("--sve", action="store_true",
                       help="obradi sve korpus/izvori/agency-agents-* divizije")
        p.add_argument("--maks-po-fajlu", type=int, default=4)
        p.add_argument("--suvo", action="store_true", help="bez troška (lažni LLM)")

    def handle(self, *args, **o):
        baza = getattr(settings, "BASE_DIR", os.getcwd())
        maks = o["maks_po_fajlu"]
        suvo = o.get("suvo")
        llm = destilator.napravi_llm(suvo)

        poslovi = self._poslovi(baza, o)

        uk_vest = uk_ul = uk_iz = uk_cena = 0
        for izvor_abs, izlaz_abs, div_ime in poslovi:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n# divizija: {div_ime}"))
            vest, ul, iz, cena = self._obradi_dir(izvor_abs, izlaz_abs, div_ime, maks, llm, suvo)
            uk_vest += vest
            uk_ul += ul
            uk_iz += iz
            uk_cena += cena

        if len(poslovi) > 1:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(
                f"ZBIR: {uk_vest} veština iz {len(poslovi)} divizija."))
            if not suvo:
                self.stdout.write(
                    f"CENA UKUPNO: ulaz {uk_ul} tok, izlaz {uk_iz} tok, "
                    f"{uk_cena}¢ ({uk_cena / 100:.2f} €).")

    def _poslovi(self, baza, o):
        if o.get("sve"):
            koren = os.path.join(baza, "korpus", "izvori")
            dirs = sorted(glob.glob(os.path.join(koren, "agency-agents-*")))
            dirs = [d for d in dirs if os.path.isdir(d)]
            if not dirs:
                raise CommandError(f"Nema nijedne agency-agents-* divizije u {koren}")
            posl = []
            for d in dirs:
                div = os.path.basename(d).replace("agency-agents-", "", 1)
                izlaz = os.path.join(baza, "korpus", "vestine", f"agency-agents-{div}.json")
                posl.append((d, izlaz, div))
            return posl

        div = o.get("divizija")
        izvor = o.get("izvor_dir") or (
            os.path.join("korpus", "izvori", f"agency-agents-{div}") if div else None)
        izlaz = o.get("izlaz") or (
            os.path.join("korpus", "vestine", f"agency-agents-{div}.json") if div else None)
        if not izvor or not izlaz:
            raise CommandError("Daj --divizija, ILI --sve, ILI (--izvor-dir i --izlaz).")
        izvor_abs = izvor if os.path.isabs(izvor) else os.path.join(baza, izvor)
        izlaz_abs = izlaz if os.path.isabs(izlaz) else os.path.join(baza, izlaz)
        div_ime = div or os.path.basename(izvor_abs.rstrip("/"))
        return [(izvor_abs, izlaz_abs, div_ime)]

    def _obradi_dir(self, izvor_abs, izlaz_abs, div_ime, maks, llm, suvo):
        if not os.path.isdir(izvor_abs):
            raise CommandError(f"Nema direktorijuma: {izvor_abs}")
        fajlovi = sorted(f for f in os.listdir(izvor_abs)
                         if f.endswith(".md") and f.lower() not in ("source.md", "readme.md"))
        if not fajlovi:
            raise CommandError(f"Nema .md definicija u {izvor_abs}")

        sve: list[dict] = []
        zbir_ul = zbir_iz = zbir_cena = 0
        for f in fajlovi:
            tekst = open(os.path.join(izvor_abs, f), encoding="utf-8").read()
            name, desc, telo = _sk_frontmatter(tekst)
            nap = (f"Destilovano iz agency-agents/{div_ime}/{f} (MIT) — "
                   "naš opis postupka, ne prepis.")
            r = destilator.destiluj(telo, naslov=name or f, opis=desc, napomena=nap,
                                    maks=maks, llm=llm, suvo=suvo)
            sve.extend(r["vestine"])
            zbir_ul += r["ul"]
            zbir_iz += r["iz"]
            zbir_cena += r["cena"]
            dij = "  [suvo]" if suvo else (
                f"  [{r['etiketa']}] ul {r['ul']} / izl {r['iz']} tok · {r['cena']}¢")
            self.stdout.write(f"{f:48} → {len(r['vestine'])} veština{dij}")

        os.makedirs(os.path.dirname(izlaz_abs), exist_ok=True)
        with open(izlaz_abs, "w", encoding="utf-8") as fh:
            json.dump(sve, fh, ensure_ascii=False, indent=2)
        rel = os.path.relpath(izlaz_abs, getattr(settings, "BASE_DIR", os.getcwd()))
        self.stdout.write(self.style.SUCCESS(f"UPISANO {len(sve)} veština → {rel}"))
        if not suvo:
            self.stdout.write(
                f"CENA: ulaz {zbir_ul} tok, izlaz {zbir_iz} tok, {zbir_cena}¢ "
                f"({zbir_cena / 100:.2f} €) za {len(fajlovi)} definicija.")
        return len(sve), zbir_ul, zbir_iz, zbir_cena
