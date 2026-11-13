"""Pojmovnik struke: uvoz i semantička pretraga stručnih termina.

    manage.py pojmovnik --uvezi
    manage.py pojmovnik --trazi "aroma vina"
    manage.py pojmovnik --stanje

Uvozi domensku terminologiju (vino, rakija, metrologija, …) u bazu znanja i
pretražuje je po smislu (ADR-0120). Služi sudiji benchmarka (ADR-0154/0155) kao
referenca i agentima kao tačna terminologija.
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.content import pojmovnik
from apps.memory.models import KnowledgeFact


class Command(BaseCommand):
    help = "Uvozi i pretražuje Pojmovnik struke (domenski termini, ADR-0154)."

    def add_arguments(self, parser):
        parser.add_argument("--uvezi", action="store_true",
                            help="Uvezi sve pojmovnike (vino/rakija + metrologija).")
        parser.add_argument("--trazi", default="",
                            help="Nađi termine po smislu (semantički, ADR-0120).")
        parser.add_argument("--granica", type=int, default=5)
        parser.add_argument("--stanje", action="store_true")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, uvezi, trazi, granica, stanje, actor, **opts):
        if sum(map(bool, (uvezi, trazi, stanje))) != 1:
            raise CommandError("Treba tačno jedno: --uvezi, --trazi, --stanje.")
        if uvezi:
            if not actor.startswith("user:"):
                raise CommandError("Pojmovnik uvozi čovek; `--actor` počinje sa `user:`.")
            with bind(actor_id=actor):
                br = pojmovnik.uvezi(actor=actor)
            self.stdout.write(self.style.SUCCESS(
                f"upisano {br['upisano']} termina iz {br['izvora']} izvora "
                f"(obrisano ranijih {br['obrisano']})"))
            return
        if trazi:
            nadjeni = pojmovnik.trazi_pojmove(trazi, granica=granica)
            if not nadjeni:
                self.stdout.write(self.style.WARNING("Nema pogodaka (ili nije uvezeno)."))
                return
            for t in nadjeni:
                izvor = f" [{t['izvor']}]" if t.get("izvor") else ""
                sin = f" (= {', '.join(t['sinonimi'])})" if t.get("sinonimi") else ""
                self.stdout.write(f"  [{t.get('domen', '')}] {t.get('termin', '')}{sin}{izvor}: "
                                  f"{t.get('definicija', '')}")
            return
        # --stanje
        if not pojmovnik.pojmovi_dostupni():
            self.stdout.write(self.style.WARNING("Pojmovnik nije uvezen."))
            return
        po_domenu = Counter(
            (f.object_json or {}).get("domen", "?")
            for f in KnowledgeFact.objects.filter(
                persona__isnull=True, predicate=pojmovnik.PREDIKAT_POJMA))
        ukupno = sum(po_domenu.values())
        self.stdout.write(self.style.SUCCESS(f"Pojmovnik: {ukupno} termina"))
        for domen, n in sorted(po_domenu.items()):
            self.stdout.write(f"  {domen}: {n}")
