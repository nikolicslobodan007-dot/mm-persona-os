"""manage.py veritas_slika — URL/fajl slike → OCR → nalazi (→ verdikt). Slice 3.1.

    veritas_slika --url https://...                  # slika sa veba
    veritas_slika --fajl /putanja/do/slike.jpg       # lokalna slika (screenshot)
    veritas_slika --url ... --proveri --maks-tvrdnji 2
    veritas_slika --url ... --suvo                    # bez mreže i troška

Za memeove/screenshotove sa ugoranim tekstom: Tesseract izvuče tekst (uz
pretprocesiranje za beli tekst na boji), pa isti `izlaz` kao `veritas_klip`
izvuče nalaze (doslovno / implicirano / tehnika) i opc. donese verdikt.
Daj TAČNO jedan ulaz: `--url` ILI `--fajl`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.memory.veritas import izlaz, slika


class Command(BaseCommand):
    help = "Veritas: pročita tekst sa slike (OCR), izvuče nalaze i (opc.) donese verdikt."

    def add_arguments(self, p):
        p.add_argument("--url", help="URL slike (meme, screenshot, foto…).")
        p.add_argument("--fajl", help="Putanja do lokalne slike (umesto --url).")
        p.add_argument("--maks-nalaza", type=int, default=6, help="Najviše izdvojenih nalaza.")
        p.add_argument("--proveri", action="store_true",
                       help="Za svaku tvrdnju donesi verdikt (pretraga + izvori).")
        p.add_argument("--maks-tvrdnji", type=int, default=3,
                       help="Koliko prvih tvrdnji proveriti (uz --proveri).")
        p.add_argument("--maks-izvora", type=int, default=4,
                       help="Najviše izvora po tvrdnji (uz --proveri).")
        p.add_argument("--suvo", action="store_true", help="Bez mreže i troška (proba).")

    def handle(self, *args, **o):
        if bool(o.get("url")) == bool(o.get("fajl")):
            raise CommandError("Daj TAČNO jedan ulaz: --url ILI --fajl.")
        izvor = o.get("fajl") or o.get("url")
        je_fajl = bool(o.get("fajl"))

        try:
            rez = slika.procitaj(izvor, suvo=o["suvo"], je_fajl=je_fajl)
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
