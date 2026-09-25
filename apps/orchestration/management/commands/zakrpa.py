"""Provera i predaja zakrpe. ADR-0038.

    manage.py zakrpa --zadatak TSK-... --iz izmena.diff --proveri
    manage.py zakrpa --zadatak TSK-... --iz izmena.diff --predaj --base 9f65d41

`--proveri` ne upisuje ništa. `--predaj` upisuje zakrpu i njen ishod — i kad je
odbijena, jer je odbijena zakrpa podatak o agentu, a ne smeće.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.orchestration import zakrpa as z
from apps.orchestration.models import CodeTask
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Provera i predaja zakrpe (ADR-0038)."

    def add_arguments(self, parser):
        parser.add_argument("--zadatak", required=True, help="TSK-...")
        parser.add_argument("--iz", required=True, help="Fajl sa unified diff-om.")
        parser.add_argument("--proveri", action="store_true")
        parser.add_argument("--predaj", action="store_true")
        parser.add_argument("--persona", default="", help="npr. P-00027")
        parser.add_argument("--base", default="", help="commit nad kojim je pisana")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, zadatak, iz, proveri, predaj, persona, base, actor, **opts):
        if proveri == predaj:
            raise CommandError("Treba tačno jedno: --proveri ili --predaj.")
        zad = CodeTask.objects.filter(public_id=zadatak).first()
        if zad is None:
            raise CommandError(f"Zadatak {zadatak} ne postoji.")
        put = Path(iz)
        if not put.exists():
            raise CommandError(f"Nema fajla {put}.")
        diff = put.read_text(encoding="utf-8", errors="replace")

        p = None
        if persona:
            p = Persona.objects.filter(public_id=persona).first()
            if p is None:
                raise CommandError(f"Persona {persona} ne postoji.")

        with bind(actor_id=actor):
            if proveri:
                self._ispisi(z.check(zad, diff, persona=p))
                return
            red = z.submit(zad, diff, persona=p, base_sha=base)
            self._ispisi(z.check(zad, diff, persona=p))
            self.stdout.write(f"\nUpisano: {red.status}")

    def _ispisi(self, nalaz: z.Nalaz):
        for g in nalaz.greske:
            self.stdout.write(self.style.ERROR(f"  zakrpa: {g}"))
        for izmena in nalaz.izmene:
            razlog = dict(nalaz.odbijeno).get(izmena.path)
            if razlog:
                self.stdout.write(self.style.ERROR(
                    f"  NE SME  {izmena.path}  ({izmena.kind}) — {razlog}"))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"  sme     {izmena.path}  ({izmena.kind})"))
        if nalaz.ok:
            self.stdout.write(self.style.SUCCESS(
                f"\nZakrpa prolazi: {len(nalaz.izmene)} putanja."))
        else:
            self.stdout.write(self.style.ERROR("\nZakrpa se ne primenjuje."))
