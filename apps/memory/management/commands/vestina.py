"""Komanda: uvoz veštine u bazu znanja — prva vrata (ADR-0074), ili spisak (ADR-0084).

Uvoz pokreće isključivo čovek, zato `--actor` mora da počne sa `user:` —
ADR-0074 insistira da materijal za ovu vrstu znanja daje čovek, agent
ništa spolja ne radi, i ta granica se proverava ovde, pre nego što se
bilo šta upiše.

Ceo posao uvoza se izvršava unutar `bind(actor_id=actor)` (api/context.py) —
isti obrazac kao `memory_eval.py` i `memory_seal.py` — jer bez toga audit
trag (api/audit.py) ne vidi proveren identitet iz `--actor` nego podrazumevani
`service:system`, čime se gubi upravo ono što ADR-0074 traži da se vidi.

`--spisak` (ADR-0084) samo čita bazu znanja — ne upisuje ništa, pa ne traži
ni `--actor` ni ostale argumente uvoza, i zato ne ulazi u `bind()` okvir.
Postoji da bi se videlo šta je već u bazi, pre nego što se nešto uveze po
drugi put. Uz `--spisak`, `--izvor` filtrira po delu naslova izvora; bez
`--spisak` to je pun naslov izvora koji se uvozi.

`--commit` i `--putanja` (ADR-0077 §3) su neobavezni: popunjavaju se samo
kada korpus dolazi iz repozitorijuma, jer isti `uri` tamo daje različit
sadržaj u različitim trenucima.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.memory.vestine import Vestina, spisak, uvezi
from common import enums as E


class Command(BaseCommand):
    help = "Uvozi veštine (postupke) u bazu znanja iz JSON datoteke, ili ih ispisuje (--spisak)."

    def add_arguments(self, parser):
        parser.add_argument("--spisak", action="store_true",
                             help="Ispiši veštine iz baze znanja, bez uvoza (ADR-0084).")
        parser.add_argument("--izvor", default="",
                             help="Uvoz: naslov izvora (KnowledgeSource), obavezan. "
                                  "Uz --spisak: filtrira po delu naslova izvora.")
        parser.add_argument("--uri", default="",
                             help="URI izvora — čovek ga navodi. Obavezan pri uvozu.")
        parser.add_argument("--licenca", default="",
                             help="Licenca materijala (LicenseBox). Obavezna pri uvozu.")
        parser.add_argument("--naziv-licence", default="",
                             help="Naziv licence — obavezan kada je --licenca SLOBODNA "
                                  "(ADR-0059 tačka 2).")
        parser.add_argument("--commit", default="",
                             help="Commit iz kog je pročitan sadržaj — samo za korpus iz "
                                  "repozitorijuma (ADR-0077 §3). Neobavezan.")
        parser.add_argument("--putanja", default="",
                             help="Putanja fajla u repozitorijumu — samo za korpus iz "
                                  "repozitorijuma (ADR-0077 §3). Neobavezan.")
        parser.add_argument("--datoteka", default="",
                             help="Putanja do JSON datoteke sa veštinama. Obavezna pri uvozu.")
        parser.add_argument("--actor", default="",
                             help="Mora da počne sa 'user:' — čovek pokreće uvoz.")

    def handle(self, *args, **options):
        if options["spisak"]:
            self._ispisi(options["izvor"])
            return
        self._uvezi(options)

    def _ispisi(self, izvor_filter: str) -> None:
        """ADR-0084 — čitljiv prikaz, kolone poravnate, bez horizontalnog skrola."""
        redovi = spisak(izvor=izvor_filter)
        if not redovi:
            if izvor_filter:
                self.stdout.write(f"Nema veština za izvor koji sadrži „{izvor_filter}”.")
            else:
                self.stdout.write("Nema upisanih veština u bazi znanja.")
            return

        w_subject = max(len("veština"), *(len(r["subject"]) for r in redovi))
        w_izvor = max(len("izvor"), *(len(r["izvor"]) for r in redovi))
        w_licenca = max(len("licenca"), *(len(r["licenca"]) for r in redovi))
        header = (f"{'veština':<{w_subject}}  {'izvor':<{w_izvor}}  "
                  f"{'licenca':<{w_licenca}}  aktivan")
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for r in redovi:
            aktivan = "da" if r["aktivan"] else "ne"
            self.stdout.write(
                f"{r['subject']:<{w_subject}}  {r['izvor']:<{w_izvor}}  "
                f"{r['licenca']:<{w_licenca}}  {aktivan}"
            )

    def _uvezi(self, options: dict) -> None:
        actor = options["actor"]
        if not actor:
            raise CommandError("--actor je obavezan.")
        if not actor.startswith("user:"):
            raise CommandError(
                "ADR-0074: --actor mora da počne sa 'user:' — ovaj uvoz pokreće čovek."
            )

        # Ceo posao uvoza ide pod proverenim identitetom iz --actor (ADR-0074),
        # da bi audit trag (api/audit.py) video coveka, a ne service:system.
        with bind(actor_id=actor):
            if not options["izvor"]:
                raise CommandError("--izvor je obavezan.")
            if not options["uri"]:
                raise CommandError("--uri je obavezan.")
            if not options["licenca"]:
                raise CommandError("--licenca je obavezan.")
            try:
                licenca = E.LicenseBox(options["licenca"])
            except ValueError as exc:
                validne = ", ".join(e.value for e in E.LicenseBox)
                raise CommandError(
                    f"Nepoznata licenca: {options['licenca']!r}. Važeće: {validne}."
                ) from exc

            naziv_licence = options["naziv_licence"]
            if licenca == E.LicenseBox.SLOBODNA and not naziv_licence:
                raise CommandError(
                    "ADR-0059: slobodna kutija mora da imenuje licencu (--naziv-licence)."
                )

            if not options["datoteka"]:
                raise CommandError("--datoteka je obavezan.")
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
                license_box=licenca,
                license_note=naziv_licence,
                commit_sha=options["commit"],
                file_path=options["putanja"],
                vestine=vestine,
                actor=actor,
            )
        self.stdout.write(self.style.SUCCESS(f"Uvezeno: {broj}"))
