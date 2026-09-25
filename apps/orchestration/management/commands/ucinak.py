"""Učinak programerskih agenata. ADR-0034 §6, ADR-0042.

    manage.py ucinak                      (svi koji su nešto radili)
    manage.py ucinak --sektor RAZVOJ
    manage.py ucinak --persona P-00027

Ono što se ne meri je ispisano na kraju, a ne prećutano: broj koji niko ne može
da potkrepi gori je od nedostajućeg.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.orchestration import ucinak as u
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Merenje rada po agentu (ADR-0034 §6)."

    def add_arguments(self, parser):
        parser.add_argument("--persona", default="")
        parser.add_argument("--sektor", default="")

    def handle(self, *args, persona, sektor, **opts):
        if persona:
            p = Persona.objects.filter(public_id=persona).first()
            if p is None:
                raise CommandError(f"Persona {persona} ne postoji.")
            redovi = [u.za_agenta(p)]
        else:
            redovi = u.za_sve(sektor)

        if not redovi:
            self.stdout.write("Nema nijednog agenta sa zadatkom ili zakrpom.")
            return

        self.stdout.write(
            f"{'AGENT':10} {'ZADACI':>7} {'GOTOVO':>7} {'ZAKRPE':>7} "
            f"{'ODBIJ.':>7} {'ZONA':>5} {'1. PUT':>7} {'NALAZI':>7}  IME")
        for r in redovi:
            prvi = "—" if r.iz_prvog_puta is None else f"{r.iz_prvog_puta:.0%}"
            zona = self.style.ERROR(f"{r.odbijenih_zbog_zone:>5}") \
                if r.odbijenih_zbog_zone else f"{r.odbijenih_zbog_zone:>5}"
            self.stdout.write(
                f"{r.persona:10} {r.zadataka:>7} {r.zavrsenih:>7} {r.zakrpa:>7} "
                f"{r.odbijenih:>7} {zona} {prvi:>7} {r.nalaza_na_rad:>7}  {r.ime}")

        blokeri = sum(r.blokera_na_rad for r in redovi)
        if blokeri:
            self.stdout.write(self.style.WARNING(
                f"\nOtvorenih i zatvorenih BLOCKER nalaza ukupno: {blokeri}."))

        self.stdout.write("\nŠta se NE meri (ADR-0034 §6 traži, izvora još nema):")
        for stavka in u.NE_MERI_SE:
            self.stdout.write(f"  · {stavka}")
