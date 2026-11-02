"""manage.py veritas_proveri — oceni tvrdnju protiv svedoka i web izvora (slice 2a).

    python manage.py veritas_proveri --tvrdnja "Ministar je rekao X" \
        --svedok "Slobodan video uživo, TV jutarnji program" \
        --izvor-url https://n1info.rs/... --izvor-url https://vreme.com/...

Svedok = prvoručni ljudski izvor (blizina 0.90). Svaki URL se dohvati (Libri
`uvoz_web`, SSRF/robots brane) i Gateway oceni da li potvrđuje/oponira tvrdnju.
Pet osa (reuse Libri `pouzdanost`) → verdikt. `--suvo` bez mreže i troška.
Pretragu izvora (da sam nađe „više strana") donosi slice 2b.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.memory.veritas import sud, verdikt


class Command(BaseCommand):
    help = "Veritas: oceni tvrdnju protiv svedoka i web izvora (pet osa + verdikt)."

    def add_arguments(self, p):
        p.add_argument("--tvrdnja", required=True, help="Tvrdnja koja se proverava.")
        p.add_argument("--svedok", action="append", default=[],
                       help="Svedok UŽIVO — najjači prvoručni izvor (ponovljivo).")
        p.add_argument("--svedok-snimak", action="append", default=[],
                       help="Svedok koji je gledao SNIMAK (ne uživo) — niži trust (ponovljivo).")
        p.add_argument("--izvor-url", action="append", default=[],
                       help="URL izvora za proveru (ponovljivo).")
        p.add_argument("--suvo", action="store_true", help="Bez mreže i troška.")

    def handle(self, *args, **o):
        tvrdnja = o["tvrdnja"]
        izvori: list[dict] = []

        for i, sv in enumerate(o["svedok"]):
            izvori.append({"vrsta": "svedok", "stav": verdikt.POTVRDJUJE,
                           "id": f"svedok-{i}"})
            self.stdout.write(f"svedok (uživo): {sv[:70]} → potvrđuje (blizina 0.90)")
        for i, sv in enumerate(o["svedok_snimak"]):
            izvori.append({"vrsta": "svedok_snimak", "stav": verdikt.POTVRDJUJE,
                           "id": f"svedok-snimak-{i}"})
            self.stdout.write(
                f"svedok (snimak): {sv[:70]} → potvrđuje (blizina 0.90, pouzdanost 0.75)")

        llm = sud._lazni_llm if o["suvo"] else sud.napravi_llm()
        for url in o["izvor_url"]:
            tekst = self._dohvati(url, o["suvo"])
            if tekst is None:
                continue
            ocena = sud.oceni_izvor(tvrdnja, tekst, llm)
            if not ocena or ocena["stav"] == "ne_pominje":
                self.stdout.write(f"izvor {url}: ne pominje tvrdnju — preskačem")
                continue
            izvori.append({"vrsta": "web", "stav": ocena["stav"], "id": url})
            self.stdout.write(f"izvor {url}: {ocena['stav']} — {ocena['obrazlozenje'][:70]}")

        r = verdikt.oceni_tvrdnju(tvrdnja, izvori)
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

    def _dohvati(self, url: str, suvo: bool):
        if suvo:
            return "(suvo — bez dohvata)"
        from apps.libri import uvoz_web
        try:
            uvoz_web.proveri_bezbedan(url)
            return uvoz_web.preuzmi(url)
        except Exception as e:  # noqa: BLE001 — dohvat sme da padne po izvoru
            self.stdout.write(self.style.WARNING(f"izvor {url}: ne mogu da dohvatim ({e})"))
            return None
