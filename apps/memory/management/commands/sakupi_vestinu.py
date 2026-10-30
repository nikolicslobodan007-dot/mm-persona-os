"""manage.py sakupi_vestinu — agent sam destiluje veštinu kroz F7 Gateway.

Prvi autonomni test „Sakupljenih vrata" sa ŽIVIM LLM-om (ne spolja u ruci):
tekst → pametna vrata (`wk_sakupljanje.sakupi_pametno`) sa `llm` = Gateway adapter
→ PREDLOG veština (status koji čeka Meta-reviziju; NE upisuje se u bazu odavde).

Primeri:
  python manage.py sakupi_vestinu --demo
  python manage.py sakupi_vestinu --tekst "Prvo ... Zatim ... Na kraju ..."
  python manage.py sakupi_vestinu --tekst-fajl /app/mk_tekst.txt --izvor "dynadot.com/..."

Napomena: za granu `destiluj` (tekst već ima postupak) ne trebaju trafilatura/ddgs.
Grane `prati_pokazivac`/`trazi_izvor` traže te pakete u kontejneru — zasebno.
"""

from __future__ import annotations

import os
import sys

from django.core.management.base import BaseCommand

# Demo: pravi procedurni srpski tekst (hladni mejl) → grana „destiluj".
_DEMO = (
    "Pre slanja napravi segmentisanu listu potencijalnih klijenata po industriji i "
    "veličini. Šalji s profesionalne adrese i vodi evidenciju kome si pisao. "
    "Otvori mejl kratkim ličnim uvodom — imenom ili konkretnim pitanjem, bez uopštenih "
    "pozdrava. Personalizuj svaku poruku primaocu i firmi. Piši kratko i aktivnim glasom: "
    "pozdrav, kuka za interes, pa jasna ponuda. Ne najavljuj prodaju prerano. Završi jednim "
    "jasnim pozivom na akciju. Dodaj jednostavan potpis i proveri pravopis. Ako nema "
    "odgovora, pošalji kratak podsetnik bez pritiska."
)


class Command(BaseCommand):
    help = "Destiluje veštinu iz teksta kroz F7 Gateway (PREDLOG, ne upisuje u bazu)."

    def add_arguments(self, p):
        p.add_argument("--tekst", help="tekst za destilaciju")
        p.add_argument("--tekst-fajl", help="putanja do tekst fajla (u kontejneru)")
        p.add_argument("--demo", action="store_true", help="koristi ugrađen demo tekst")
        p.add_argument("--izvor", default="ručni unos", help="opis izvora (ide u napomene)")

    def handle(self, *args, **o):
        # wk-moduli su u apps/memory/sakupljanje/ (plain dir na sys.path).
        paket = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "sakupljanje")
        if paket not in sys.path:
            sys.path.insert(0, paket)
        import wk_sakupljanje as S
        from gateway_llm import napravi_llm

        if o.get("demo"):
            tekst = _DEMO
        elif o.get("tekst"):
            tekst = o["tekst"]
        elif o.get("tekst_fajl"):
            with open(o["tekst_fajl"], encoding="utf-8") as f:
                tekst = f.read()
        else:
            self.stderr.write("Daj --demo, --tekst ili --tekst-fajl.")
            return

        llm = napravi_llm()
        rez = S.sakupi_pametno(
            tekst, dozvole={S.DOZVOLA_SAKUPLJANJE, S.DOZVOLA_WEB},
            llm=llm, izvor_opis=o["izvor"],
        )

        self.stdout.write(f"PUT: {rez.get('put')}  | {rez.get('obrazlozenje','')}")
        if not rez.get("ok"):
            self.stdout.write(f"NEUSPEH: {rez.get('razlog')}")
            return

        # Dijagnostika Gateway-a (dokaz da je išao spoljni model, ne lokalni šablon).
        g = getattr(llm, "last", None)
        if g is not None:
            self.stdout.write(
                f"GATEWAY: {g.provider}/{g.model} | ulaz {g.input_tokens} tok, "
                f"izlaz {g.output_tokens} tok | cena {g.amount_eur_cents}¢"
                + (f" | fallbacks: {g.fallbacks}" if g.fallbacks else ""))

        predlozi = rez.get("predlozi", [])
        self.stdout.write(f"DESTILOVANO: {len(predlozi)} PREDLOG veština (status čeka GO)\n")
        for i, v in enumerate(predlozi, 1):
            self.stdout.write(f"[{i}] {v.vestina['ime']}  (pouzdanost {v.vestina['pouzdanost']})")
            for k in v.vestina["koraci"]:
                self.stdout.write(f"     • {k}")
            self.stdout.write(f"     napomene: {v.vestina['napomene']}")
            self.stdout.write(f"     status: {v.status} | stiže agentima: {v.stize_agentima}\n")
