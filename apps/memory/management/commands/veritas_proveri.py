"""manage.py veritas_proveri — oceni tvrdnju protiv svedoka i izvora (slice 2a + 2b).

    # ručni izvori:
    veritas_proveri --tvrdnja "..." --svedok "..." --izvor-url https://...
    # autonomna pretraga (Brave, slice 2b):
    veritas_proveri --tvrdnja "..." --pretrazi --maks-izvora 5

Svedok UŽIVO = najjači prvoručni izvor (blizina 0.90); `--svedok-snimak` niži trust.
`--pretrazi`: Veritas SAM nađe izvore (Brave Search). Svaki URL se dohvati
(Libri `uvoz_web`, SSRF/robots brane), Gateway oceni stav, pa verdikt (pet osa).
`--suvo` bez mreže i troška.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.memory.veritas import pretraga, sud, verdikt


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
        tvrdnja = o["tvrdnja"]
        izvori: list[dict] = []

        for i, sv in enumerate(o["svedok"]):
            izvori.append({"vrsta": "svedok", "stav": verdikt.POTVRDJUJE, "id": f"svedok-{i}"})
            self.stdout.write(f"svedok (uživo): {sv[:70]} → potvrđuje (blizina 0.90)")
        for i, sv in enumerate(o["svedok_snimak"]):
            izvori.append({"vrsta": "svedok_snimak", "stav": verdikt.POTVRDJUJE,
                           "id": f"svedok-snimak-{i}"})
            self.stdout.write(
                f"svedok (snimak): {sv[:70]} → potvrđuje (blizina 0.90, pouzdanost 0.75)")

        llm = sud._lazni_llm if o["suvo"] else sud.napravi_llm()

        urlovi = list(o["izvor_url"])
        if o["pretrazi"]:
            urlovi += self._pretrazi(tvrdnja, o["maks_izvora"], o["suvo"])

        videno = {iz["id"] for iz in izvori}
        for url in urlovi:
            if url in videno:
                continue
            videno.add(url)
            self._dodaj_url(url, tvrdnja, llm, izvori, o["suvo"])

        self._ispisi(verdikt.oceni_tvrdnju(tvrdnja, izvori))

    def _pretrazi(self, tvrdnja, maks, suvo):
        trazi = pretraga._lazni if suvo else pretraga.pretrazi
        try:
            kandidati = trazi(tvrdnja, maks)
        except Exception as e:  # noqa: BLE001 — pretraga sme da padne, nastavi bez nje
            self.stdout.write(self.style.WARNING(f"pretraga pala: {e}"))
            return []
        self.stdout.write(self.style.MIGRATE_HEADING(f"# pretraga: {len(kandidati)} kandidata"))
        for k in kandidati:
            self.stdout.write(f"  {k['url']}")
        return [k["url"] for k in kandidati]

    def _dodaj_url(self, url, tvrdnja, llm, izvori, suvo):
        tekst = self._dohvati(url, suvo)
        if tekst is None:
            return
        ocena = sud.oceni_izvor(tvrdnja, tekst, llm)
        if not ocena or ocena["stav"] == "ne_pominje":
            self.stdout.write(f"izvor {url}: ne pominje tvrdnju — preskačem")
            return
        izvori.append({"vrsta": "web", "stav": ocena["stav"], "id": url})
        self.stdout.write(f"izvor {url}: {ocena['stav']} — {ocena['obrazlozenje'][:70]}")

    def _dohvati(self, url, suvo):
        if suvo:
            return "(suvo — bez dohvata)"
        from apps.libri import uvoz_web
        try:
            uvoz_web.proveri_bezbedan(url)
            return uvoz_web.preuzmi(url)
        except Exception as e:  # noqa: BLE001 — dohvat sme da padne po izvoru
            self.stdout.write(self.style.WARNING(f"izvor {url}: ne mogu da dohvatim ({e})"))
            return None

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
