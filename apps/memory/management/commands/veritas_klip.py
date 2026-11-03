"""manage.py veritas_klip — URL klipa → transkript → nalazi (→ verdikt). Slice 3 + 4.

    veritas_klip --url https://...                      # transkript + nalazi (tri sloja)
    veritas_klip --url https://... --proveri            # + verdikt za svaku tvrdnju (Brave)
    veritas_klip --url https://... --proveri --maks-tvrdnji 3 --maks-izvora 4
    veritas_klip --url https://... --suvo               # bez mreže i troška

Tok: yt-dlp skine audio → ffmpeg 16 kHz mono mp3 → Gateway TRANSCRIBE (Groq
Whisper) → transkript → `nalaz` izvuče tvrdnje u tri sloja. Sa `--proveri`,
svaka doslovna tvrdnja ide kroz `lanac` (pretraga → sud → verdikt po pet osa) —
pun lanac: snimak → tvrdnja → verdikt.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.memory.veritas import klip, lanac, nalaz, sud


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

        if o["proveri"]:
            self._proveri(nalazi, o)

    def _proveri(self, nalazi, o):
        sud_llm = sud._lazni_llm if o["suvo"] else sud.napravi_llm()
        koliko = min(o["maks_tvrdnji"], len(nalazi))
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"## Provera {koliko} tvrdnje/a:"))
        for i, n in enumerate(nalazi[:koliko], 1):
            tvrdnja = (n.get("doslovna") or "").strip()
            if not tvrdnja:
                continue
            self.stdout.write("")
            self.stdout.write(f"[{i}] {tvrdnja}")
            rez = lanac.proveri_tvrdnju(
                tvrdnja, llm=sud_llm, maks_izvora=o["maks_izvora"], suvo=o["suvo"],
                pretrazi=True, na_dogadjaj=self._kratko)
            r = rez["verdikt"]
            red = (f"    VERDIKT: {r['verdikt']} (izvora {r['izvori']}, "
                   f"saglasnih {r['saglasnih']}, protivrečnih {r['protivrecnih']})")
            if r.get("ose"):
                red += f" · ukupno {r['ose']['ukupno']}"
            self.stdout.write(self.style.SUCCESS(red))
            if r.get("sporno_tumacenje"):
                self.stdout.write(self.style.WARNING(
                    f"    tumačenje sporno ({r['sporno_tumacenje']}) — izrečeno potvrđeno, "
                    "značenje osporeno."))

    def _kratko(self, tip, d):
        if tip == "pretraga":
            self.stdout.write(f"    pretraga: {len(d['kandidati'])} izvora")
        elif tip == "pretraga_pala":
            self.stdout.write(self.style.WARNING(f"    pretraga pala: {d['greska']}"))
