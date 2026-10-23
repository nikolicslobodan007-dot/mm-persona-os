"""Komanda `libri` — uvoz PDF-a u sloj znanja (ADR-0031, sloj 2).

Uvoz pokreće čovek (ADR-0074): `--actor` mora da počne sa `user:`. Posao ide
unutar `bind(actor_id=actor)` (api/context.py) da audit vidi proveren identitet
— isti obrazac kao `vestina` i `memory_eval`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.libri.uvoz import UvozError, uvezi


class Command(BaseCommand):
    help = "Uvozi PDF u sloj znanja (LKP blokovi): libri uvezi --iz <PDF> ..."

    def add_arguments(self, parser):
        parser.add_argument("radnja", choices=["uvezi"],
                            help="Radnja (za sada samo: uvezi).")
        parser.add_argument("--iz", default="", help="Putanja do PDF-a.")
        parser.add_argument("--naslov", default="",
                            help="Naslov dokumenta (podrazumevano: ime fajla).")
        parser.add_argument("--licenca", default="",
                            help="LicenseBox: SLOBODNA, ZARAZNA, ZABRANJENA, NEPOZNATA.")
        parser.add_argument("--naziv-licence", default="",
                            help="Naziv licence — obavezan kad je --licenca SLOBODNA.")
        parser.add_argument("--actor", default="",
                            help="Mora da počne sa 'user:' (čovek uvozi).")

    def handle(self, *args, **options):
        iz = options["iz"]
        actor = options["actor"]
        if not iz:
            raise CommandError("uvezi traži --iz <PDF>.")
        if not actor.startswith("user:"):
            raise CommandError(
                "--actor mora da počne sa 'user:' (ADR-0074 — čovek uvozi)."
            )
        if not options["licenca"]:
            raise CommandError("uvezi traži --licenca.")
        try:
            with bind(actor_id=actor):
                dok = uvezi(
                    iz,
                    naslov=options["naslov"],
                    licenca=options["licenca"],
                    naziv_licence=options["naziv_licence"],
                )
        except UvozError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(
            f"Uvezeno: {dok.document_id} „{dok.title}” — "
            f"{dok.pages} str., {dok.blocks.count()} blokova."
        ))
