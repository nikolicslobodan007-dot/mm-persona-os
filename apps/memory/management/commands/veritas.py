"""manage.py veritas — Veritas desk (slice 1): tekst → nalaz (tri sloja po tvrdnji).

    python manage.py veritas --tekst "Ministar je rekao ..."
    python manage.py veritas --datoteka transkript.txt --maks 8
    python manage.py veritas --tekst "..." --suvo     # bez troška (lažni LLM)

Prvo pokazivač-detektor proceni ulaz (sadržaj / pokazivač / prazno). Ako tekst
nosi sopstvene tvrdnje → vadi nalaze kroz Gateway. Ako pokazuje na izvor
(link/fraza) → javi i stani (praćenje pokazivača je sledeći slice).
Veritas vadi i uokviruje tvrdnje; NE sudi o istini (to je provera, slice 2).
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from apps.memory.veritas import nalaz, pokazivac


class Command(BaseCommand):
    help = "Veritas: iz teksta izvuci tvrdnje i uokvirivanje (tri sloja)."

    def add_arguments(self, p):
        p.add_argument("--tekst", default="", help="Tekst za analizu (direktno).")
        p.add_argument("--datoteka", default="", help="Putanja do .txt sa tekstom.")
        p.add_argument("--maks", type=int, default=6, help="Najviše tvrdnji.")
        p.add_argument("--suvo", action="store_true", help="Bez troška (lažni LLM).")

    def handle(self, *args, **o):
        tekst = o.get("tekst") or ""
        if o.get("datoteka"):
            if not os.path.isfile(o["datoteka"]):
                raise CommandError(f"Nema datoteke: {o['datoteka']}")
            tekst = open(o["datoteka"], encoding="utf-8").read()
        if not tekst.strip():
            raise CommandError("Daj --tekst ili --datoteka.")

        proc = pokazivac.analiziraj(tekst)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# pokazivač: {proc['tip']} → {proc['preporuka']}"))
        self.stdout.write(f"  {proc['obrazlozenje']}")
        if proc["pokazivaci"]:
            meta = ", ".join(f"{p['vrsta']}:{p['vrednost']}" for p in proc["pokazivaci"])
            self.stdout.write(f"  pokazivači: {meta}")

        if proc["preporuka"] != "analiziraj":
            self.stdout.write(self.style.WARNING(
                "  → tekst ne nosi sopstvene tvrdnje; praćenje pokazivača je "
                "sledeći slice. Stajem."))
            return

        if o.get("suvo"):
            llm = nalaz._lazni_llm
            g = None
        else:
            llm = nalaz.napravi_llm()
            g = llm

        nalazi = nalaz.izvuci_nalaze(tekst, llm, o["maks"])
        self.stdout.write("")
        for n in nalazi:
            self.stdout.write(self.style.SUCCESS(f"• {n['doslovna']}"))
            if n["implicirana"]:
                self.stdout.write(f"    implicira: {n['implicirana']}")
            self.stdout.write(f"    tehnika: {n['tehnika']} · pouzdanost: {n['pouzdanost']}")
            if n["za_proveru"]:
                self.stdout.write(f"    za proveru: {n['za_proveru']}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"NALAZA: {len(nalazi)}"))
        last = getattr(g, "last", None) if g is not None else None
        if last is not None:
            self.stdout.write(
                f"CENA: [{last.provider}/{last.model}] ul {last.input_tokens} / izl "
                f"{last.output_tokens} tok · {last.amount_eur_cents}¢")
