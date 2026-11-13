"""Propisi: uvoz i semantička pretraga članova zakona/podzakonskih akata.

    manage.py propisi --uvezi
    manage.py propisi --trazi "overavanje merila"
    manage.py propisi --clan 26
    manage.py propisi --stanje

Uvozi propise (po jedan član = jedan zapis) u bazu znanja i pretražuje ih po
smislu (ADR-0120). Izvor je verni tekst; modul citira član, ne presuđuje
usaglašenost (ADR-0157).
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.content import propisi
from apps.memory.models import KnowledgeFact


class Command(BaseCommand):
    help = "Uvozi i pretražuje Propise (članovi zakona, ADR-0157)."

    def add_arguments(self, parser):
        parser.add_argument("--uvezi", action="store_true",
                            help="Uvezi sve propise iz IZVORI.")
        parser.add_argument("--trazi", default="",
                            help="Nađi članove po smislu (semantički, ADR-0120).")
        parser.add_argument("--clan", type=int, default=0,
                            help="Vrati tačno određen član po broju.")
        parser.add_argument("--propis", default="",
                            help="Ograniči na jedan propis (po nazivu `propis`).")
        parser.add_argument("--granica", type=int, default=5)
        parser.add_argument("--stanje", action="store_true")
        parser.add_argument("--actor", default="user:slobodan")

    def _ispisi(self, c: dict):
        glava = f" [{c['glava']}]" if c.get("glava") else ""
        naslov = f" — {c['naslov']}" if c.get("naslov") else ""
        self.stdout.write(self.style.SUCCESS(
            f"{c.get('propis', '')}, Član {c.get('clan', '')}{naslov}{glava}"))
        self.stdout.write(c.get("tekst", ""))
        self.stdout.write("")

    def handle(self, *args, uvezi, trazi, clan, propis, granica, stanje, actor, **opts):
        prop = propis or None
        if sum(map(bool, (uvezi, trazi, clan, stanje))) != 1:
            raise CommandError("Treba tačno jedno: --uvezi, --trazi, --clan, --stanje.")
        if uvezi:
            if not actor.startswith("user:"):
                raise CommandError("Propise uvozi čovek; `--actor` počinje sa `user:`.")
            with bind(actor_id=actor):
                br = propisi.uvezi(actor=actor)
            self.stdout.write(self.style.SUCCESS(
                f"upisano {br['upisano']} članova iz {br['izvora']} propisa "
                f"(obrisano ranijih {br['obrisano']})"))
            return
        if clan:
            c = propisi.clan(clan, propis=prop)
            if not c:
                self.stdout.write(self.style.WARNING("Nema tog člana (ili nije uvezeno)."))
                return
            self._ispisi(c)
            return
        if trazi:
            nadjeni = propisi.trazi_clanove(trazi, granica=granica, propis=prop)
            if not nadjeni:
                self.stdout.write(self.style.WARNING("Nema pogodaka (ili nije uvezeno)."))
                return
            for c in nadjeni:
                self._ispisi(c)
            return
        # --stanje
        if not propisi.propisi_dostupni():
            self.stdout.write(self.style.WARNING("Propisi nisu uvezeni."))
            return
        po_propisu = Counter(
            (f.object_json or {}).get("propis", "?")
            for f in KnowledgeFact.objects.filter(
                persona__isnull=True, predicate=propisi.PREDIKAT_CLANA))
        ukupno = sum(po_propisu.values())
        self.stdout.write(self.style.SUCCESS(f"Propisi: {ukupno} članova"))
        for prop_naziv, n in sorted(po_propisu.items()):
            self.stdout.write(f"  {prop_naziv}: {n}")
