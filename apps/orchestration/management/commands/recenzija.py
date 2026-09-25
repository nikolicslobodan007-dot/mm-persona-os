"""Uvoz mašinske recenzije u zadatak. ADR-0036.

    ocr review --from main --to grana --format sarif --output nalaz.sarif
    manage.py recenzija --zadatak TSK-... --sarif nalaz.sarif

Uvoz **ne zatvara** kapiju `review` — mašinska recenzija je prva kapija, ne presuda.
Kad recenzent presudi:

    manage.py zadatak --zadatak TSK-... --kapija review --prosla
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.orchestration import recenzija as uvoz
from apps.orchestration.models import CodeTask
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Uvozi SARIF izveštaj mašinske recenzije u nalaze zadatka (ADR-0036)."

    def add_arguments(self, parser):
        parser.add_argument("--zadatak", required=True, help="TSK-...")
        parser.add_argument("--sarif", required=True, help="Putanja do SARIF fajla.")
        parser.add_argument("--izvor", default="", help="Podrazumevano ime alata iz izveštaja.")
        parser.add_argument("--recenzent", default="", help="npr. P-00027, ako ga ima.")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, zadatak, sarif, izvor, recenzent, actor, **opts):
        z = CodeTask.objects.filter(public_id=zadatak).first()
        if z is None:
            raise CommandError(f"Zadatak {zadatak} ne postoji.")
        p = None
        if recenzent:
            p = Persona.objects.filter(public_id=recenzent).first()
            if p is None:
                raise CommandError(f"Persona {recenzent} ne postoji.")

        with bind(actor_id=actor):
            try:
                izvestaj = uvoz.load_sarif(sarif)
                stanje = uvoz.import_sarif(z, izvestaj, source=izvor, reviewer=p)
            except uvoz.TaskError as e:
                raise CommandError(f"{e.code}: {e}") from e

        self.stdout.write(f"{z.public_id} · izvor: {stanje['izvor']}")
        self.stdout.write(self.style.SUCCESS(f"  uvezeno:       {stanje['uvezeno']}"))
        if stanje["vec_postoji"]:
            self.stdout.write(f"  već postoji:   {stanje['vec_postoji']}")
        if stanje["bez_putanje"]:
            self.stdout.write(f"  bez lokacije:  {stanje['bez_putanje']}")
        if stanje["bez_teksta"]:
            self.stdout.write(f"  bez tvrdnje:   {stanje['bez_teksta']}")
        for naziv, kljuc in (("van zadatka", "van_zadatka"),
                             ("ZAŠTIĆENA ZONA", "zasticena_zona")):
            putanje = sorted(set(stanje[kljuc]))
            if putanje:
                stil = self.style.WARNING if kljuc == "van_zadatka" else self.style.ERROR
                self.stdout.write(stil(
                    f"  {naziv}: {len(stanje[kljuc])} nalaz(a) — nisu vezani za zadatak"))
                for put in putanje[:10]:
                    self.stdout.write(f"      {put}")
        if stanje["bezbednost"]:
            self.stdout.write(self.style.ERROR(
                f"  bezbednost: {stanje['bezbednost']} nalaz(a) najviše težine — pogledaj ih."))
        self.stdout.write(
            "  Kapija `review` nije dirana — mašinska recenzija je prva kapija, ne presuda.")
