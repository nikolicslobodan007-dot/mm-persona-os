"""manage.py veritas_klip — URL klipa → transkript → nalazi (tri sloja). Slice 3, ADR-0125.

    veritas_klip --url https://...                 # skine, transkribuje, izvuče nalaze
    veritas_klip --url https://... --maks-nalaza 6
    veritas_klip --url https://... --suvo          # bez mreže i troška (probni transkript)

Tok: yt-dlp skine audio → ffmpeg 16 kHz mono mp3 → Gateway TRANSCRIBE (Groq
Whisper) → transkript → `nalaz` izvuče tvrdnje u tri sloja (doslovno,
implicirano, tehnika). Verdikt protiv izvora je zaseban korak (`veritas_proveri`).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.memory.veritas import klip, nalaz


class Command(BaseCommand):
    help = "Veritas: skine klip, transkribuje (Groq Whisper) i izvuče nalaze (tri sloja)."

    def add_arguments(self, p):
        p.add_argument("--url", required=True, help="URL videa/audija (YouTube, X, link…).")
        p.add_argument("--maks-nalaza", type=int, default=6, help="Najviše izdvojenih nalaza.")
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

        if not transkript.strip():
            self.stdout.write("Prazan transkript — nema šta da se izvuče.")
            return

        llm = nalaz._lazni_llm if o["suvo"] else nalaz.napravi_llm()
        nalazi = nalaz.izvuci_nalaze(transkript, llm, o["maks_nalaza"])
        if not nalazi:
            self.stdout.write("Nema izdvojenih nalaza.")
            return

        self.stdout.write(f"# {len(nalazi)} nalaz(a):")
        for i, n in enumerate(nalazi, 1):
            self.stdout.write(
                f"— Nalaz {i} [{n.get('tehnika', '?')}] pouzdanost {n.get('pouzdanost', '?')}")
            self.stdout.write(f"   doslovno:    {n.get('doslovna', '')}")
            self.stdout.write(f"   implicirano: {n.get('implicirana', '')}")
            self.stdout.write(f"   za proveru:  {n.get('za_proveru', '')}")
