"""manage.py veritas_slika — URL slike → OCR → nalazi (→ verdikt). Slice 3.1.

    veritas_slika --url https://...                 # OCR tekst + nalazi (tri sloja)
    veritas_slika --url https://... --proveri        # + verdikt za svaku tvrdnju
    veritas_slika --url https://... --suvo           # bez mreže i troška

Za memeove/screenshotove sa ugoranim tekstom: Tesseract izvuče tekst, pa isti
`izlaz` kao `veritas_klip` izvuče nalaze (doslovno / implicirano / tehnika) i
opc. donese verdikt. Sarkazam/ironija se vide kad doslovno i implicirano idu
u suprotnim smerovima.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.memory.veritas import izlaz, slika


class Command(BaseCommand):
    help = "Veritas: pročita tekst sa slike (OCR), izvuče nalaze i (opc.) donese verdikt."

    def add_arguments(self, p):
        p.add_argument("--url", required=True, help="URL slike (meme, screenshot, foto…).")
        p.add_argument("--maks-nalaza", type=int, default=6, help="Najviše izdvojenih nalaza.")
        p.add_argument("--proveri", action="store_true",
                       help="Za svaku tvrdnju donesi verdikt (pretraga + izvori).")
        p.add_argument("--maks-tvrdnji", type=int, default=3,
                       help="Koliko prvih tvrdnji proveriti (uz --proveri).")
        p.add_argument("--maks-izvora", type=int, default=4,
                       help="Najviše izvora po tvrdnji (uz --proveri).")
        p.add_argument("--suvo", action="store_true", help="Bez mreže i troška (proba).")

    def handle(self, *args, **o):
        try:
            rez = slika.procitaj(o["url"], suvo=o["suvo"])
        except slika.SlikaGreska as e:
            self.stderr.write(self.style.ERROR(f"slika pala: {e}"))
            return

        tekst = rez["tekst"] or ""
        self.stdout.write(self.style.SUCCESS("# OCR tekst"))
        if rez.get("asset_id"):
            self.stdout.write(f"# asset: {rez['asset_id']}  izvor: {rez['izvor_url']}")
        self.stdout.write(tekst[:4000])
        self.stdout.write("")

        izlaz.prikazi_nalaze(self, tekst, o)
