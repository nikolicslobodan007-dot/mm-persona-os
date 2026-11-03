"""manage.py veritas_proveri — oceni tvrdnju protiv svedoka i izvora (slice 2a + 2b + 4).

    # ručni izvori:
    veritas_proveri --tvrdnja "..." --svedok "..." --izvor-url https://...
    # autonomna pretraga (Brave, slice 2b):
    veritas_proveri --tvrdnja "..." --pretrazi --maks-izvora 5

Svedok UŽIVO = najjači prvoručni izvor (blizina 0.90); `--svedok-snimak` niži trust.
`--pretrazi`: Veritas SAM nađe izvore (Brave Search). Svaki URL se dohvati
(Libri `uvoz_web`), Gateway oceni stav, pa verdikt (pet osa). `--suvo` bez mreže.

Tok (pretraga → sud → verdikt) živi u `veritas.lanac`; ovde je samo CLI i ispis.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.memory.veritas import lanac, sud


class Command(BaseCommand):
    help = "Veritas: oceni tvrdnju protiv svedoka i izvora (pet osa + verdikt)."

    def add_arguments(self, p):
        p.add_argument("--tvrdnja", required=True, help="Tvrdnja koja se proverava.")
        p.add_argument("--svedok", action="append", default=[],
                       help="Svedok UŽIVO — najjači prvoručni izvor (ponovljivo).")
        p.add_argument("--svedok-snimak", action="append", default=[],
                       help="Svedok koji je gledao SNIMAK (ne uživo) — niži trust (ponovljivo).")
        p.add_argument("--izvor-url", action="append", default=[],
                       help="URL izvora za proveru (ponovljivo).")
        p.add_argument("--pretrazi", action="store_true",
                       help="Autonomno nađi izvore (Brave Search) iz tvrdnje.")
        p.add_argument("--maks-izvora", type=int, default=5,
                       help="Najviše izvora iz pretrage.")
        p.add_argument("--suvo", action="store_true", help="Bez mreže i troška.")

    def handle(self, *args, **o):
        svedoci = [{"vrsta": "svedok", "opis": s} for s in o["svedok"]]
        svedoci += [{"vrsta": "svedok_snimak", "opis": s} for s in o["svedok_snimak"]]

        llm = sud._lazni_llm if o["suvo"] else sud.napravi_llm()
        rez = lanac.proveri_tvrdnju(
            o["tvrdnja"], llm=llm, maks_izvora=o["maks_izvora"], suvo=o["suvo"],
            pretrazi=o["pretrazi"], svedoci=svedoci, dodatni_urlovi=o["izvor_url"],
            na_dogadjaj=self._dogadjaj)
        self._ispisi(rez["verdikt"])

    def _dogadjaj(self, tip, d):
        if tip == "svedok":
            if d["vrsta"] == "svedok_snimak":
                self.stdout.write(
                    f"svedok (snimak): {d['opis'][:70]} → potvrđuje "
                    "(blizina 0.90, pouzdanost 0.75)")
            else:
                self.stdout.write(f"svedok (uživo): {d['opis'][:70]} → potvrđuje (blizina 0.90)")
        elif tip == "pretraga":
            k = d["kandidati"]
            self.stdout.write(self.style.MIGRATE_HEADING(f"# pretraga: {len(k)} kandidata"))
            for url in k:
                self.stdout.write(f"  {url}")
        elif tip == "pretraga_pala":
            self.stdout.write(self.style.WARNING(f"pretraga pala: {d['greska']}"))
        elif tip == "izvor":
            self.stdout.write(f"izvor {d['url']}: {d['stav']} — {d['obrazlozenje'][:70]}")
        elif tip == "izvor_preskocen":
            self.stdout.write(f"izvor {d['url']}: {d['razlog']} — preskačem")

    def _ispisi(self, r):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"VERDIKT: {r['verdikt']}  (izvora {r['izvori']}, saglasnih "
            f"{r['saglasnih']}, protivrečnih {r['protivrecnih']})"))
        if r["ose"]:
            z = r["ose"]
            self.stdout.write(
                f"  ose: pouzdanost {z['pouzdanost']} · blizina {z['blizina']} · "
                f"potkrepljenost {z['potkrepljenost']} · nezavisnost {z['nezavisnost']} · "
                f"stabilnost {z['stabilnost']} → ukupno {z['ukupno']}")
        if r.get("sporno_tumacenje"):
            dodatak = ""
            if r.get("svedok_uzivo"):
                dodatak = (" Svedok uživo (ceo nastup) slabi odbranu da je "
                           "izvučeno iz konteksta.")
            self.stdout.write(self.style.WARNING(
                f"  napomena: tumačenje sporno ({r['sporno_tumacenje']} izvor/a) — "
                f"potvrđeno da je IZREČENO, značenje osporeno.{dodatak}"))
