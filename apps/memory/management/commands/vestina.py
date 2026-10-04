"""Komanda: uvoz veštine u bazu znanja — prva vrata (ADR-0074).

Pokreće je isključivo čovek, zato `--actor` mora da počne sa `user:` —
ADR-0074 insistira da materijal za ovu vrstu znanja daje čovek, agent
ništa spolja ne radi, i ta granica se proverava ovde, pre nego što se
bilo šta upiše.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.memory.vestine import Vestina, uvezi
from common import enums as E


class Command(BaseCommand):
    help = "Uvozi veštine (postupke) u bazu znanja iz JSON datoteke."

    def add_arguments(self, parser):
        parser.add_argument("--izvor", required=True, help="Naslov izvora (KnowledgeSource).")
        parser.add_argument("--uri", required=True, help="URI izvora — čovek ga navodi.")
        parser.add_argument("--licenca", required=True,
                             choices=[e.value for e in E.LicenseBox],
                             help="Licenca materijala (LicenseBox).")
        parser.add_argument("--datoteka", required=True,
                             help="Putanja do JSON datoteke sa veštinama.")
        parser.add_argument("--actor", required=True,
                             help="Mora da počne sa 'user:' — čovek pokreće uvoz.")

    def handle(self, *args, **options):
        actor = options["actor"]
        if not actor.startswith("user:"):
            raise CommandError(
                "ADR-0074: --actor mora da počne sa 'user:' — ovaj uvoz pokreće čovek."
            )

        putanja = Path(options["datoteka"])
        if not putanja.exists():
            raise CommandError(f"Datoteka ne postoji: {putanja}")

        sirovo = json.loads(putanja.read_text(encoding="utf-8"))
        vestine = [
            Vestina(
                ime=stavka["ime"],
                koraci=list(stavka["koraci"]),
                napomene=stavka.get("napomene", ""),
                pouzdanost=float(stavka["pouzdanost"]),
            )
            for stavka in sirovo
        ]

        broj = uvezi(
            naslov_izvora=options["izvor"],
            uri=options["uri"],
            license_box=E.LicenseBox(options["licenca"]),
            vestine=vestine,
            actor=actor,
        )
        self.stdout.write(self.style.SUCCESS(f"Uvezeno: {broj}"))
