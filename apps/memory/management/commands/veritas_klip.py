"""manage.py veritas_klip — URL klipa → transkript → nalazi (→ verdikt). Slice 3 + 4.

    veritas_klip --url https://...                      # transkript + nalazi (tri sloja)
    veritas_klip --url https://... --proveri            # + verdikt za svaku tvrdnju (Brave)
    veritas_klip --url https://... --proveri --maks-tvrdnji 3 --maks-izvora 4
    veritas_klip --url https://... --suvo               # bez mreže i troška

Tok: yt-dlp skine audio → ffmpeg 16 kHz mono mp3 → Gateway TRANSCRIBE (Groq
Whisper) → transkript → `izlaz` izvuče nalaze (i opc. verdikt). Isti prikaz
deli sa `veritas_slika` (OCR).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.memory.veritas import izlaz, klip


class Command(BaseCommand):
    help = "Veritas: skine klip, transkribuje (Groq), izvuče nalaze i (opc.) donese verdikt."

    def add_arguments(self, p):
        p.add_argument("--url", required=True, help="URL videa/audija (YouTube, X, link…).")
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
            rez = klip.transkribuj(o["url"], suvo=o["suvo"])
        except klip.KlipGreska as e:
            self.stderr.write(self.style.ERROR(f"klip pao: {e}"))
            return

        transkript = rez["transkript"] or ""
        sek = (rez["trajanje_ms"] or 0) // 1000
        self.stdout.write(self.style.SUCCESS(
            f"# transkript ({sek}s · {rez['provider']}/{rez['model']} · {rez['cena_centi']}¢)"))
        if rez.get("asset_id"):
            self.stdout.write(f"# asset: {rez['asset_id']}  izvor: {rez['izvor_url']}")
        self.stdout.write(transkript[:4000])
        self.stdout.write("")

        izlaz.prikazi_nalaze(self, transkript, o)
