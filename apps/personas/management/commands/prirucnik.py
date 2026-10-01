"""Priručnik radnog mesta — upis i pregled. ADR-0060.

    manage.py prirucnik --mesto RAZ-PRO --spisak
    manage.py prirucnik --mesto RAZ-PRO --upisi
    manage.py prirucnik --mesto RAZ-PRO --ugasi nov-fajl --zasto "..."
    manage.py prirucnik --mesto RAZ-PRO --prompt

Ova pravila idu u **svaki** prompt za pisanje koda na tom radnom mestu. Zato se
upisuju i gase rukom, uz potpis čoveka — priručnik koji sam sebe menja nije opis
posla nego samozvanje (ADR-0060 §5).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.personas import prirucnik
from apps.personas.prirucnici import JEZGRA


class Command(BaseCommand):
    help = "Priručnik radnog mesta: upis, pregled i gašenje pravila (ADR-0060)."

    def add_arguments(self, parser):
        parser.add_argument("--mesto", required=True, help="Šifra radnog mesta, npr. RAZ-PRO.")
        parser.add_argument("--spisak", action="store_true")
        parser.add_argument("--upisi", action="store_true")
        parser.add_argument("--prompt", action="store_true",
                            help="Ispiši odeljak tačno onako kako ga model vidi.")
        parser.add_argument("--ugasi", default="", help="Ključ pravila.")
        parser.add_argument("--zasto", default="")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, mesto, spisak, upisi, prompt, ugasi, zasto, actor, **opts):
        if not actor.startswith("user:"):
            raise CommandError("Priručnik postavlja čovek; `--actor` počinje sa `user:`.")
        if sum(map(bool, (spisak, upisi, prompt, ugasi))) != 1:
            raise CommandError("Treba tačno jedno: --spisak, --upisi, --prompt ili --ugasi.")
        with bind(actor_id=actor):
            if spisak:
                return self._spisak(mesto)
            if prompt:
                return self._prompt(mesto)
            if upisi:
                return self._upisi(mesto, actor)
            return self._ugasi(mesto, ugasi, zasto, actor)

    def _spisak(self, mesto: str) -> None:
        redovi = prirucnik.spisak(mesto, i_ugasena=True)
        if not redovi:
            self.stdout.write(self.style.ERROR(f"{mesto}: priručnik nije upisan."))
            return
        for r in redovi:
            stanje = (self.style.SUCCESS("aktivno") if r.is_active
                      else self.style.ERROR("ugašeno"))
            self.stdout.write(f"{r.sort_order:3}. {r.key:20} {stanje}")
            self.stdout.write(f"     {r.text}")
            self.stdout.write(f"     izvor: {r.source}")
            if not r.is_active:
                self.stdout.write(f"     ugasio {r.retired_by}: {r.retired_reason}")

    def _prompt(self, mesto: str) -> None:
        odeljak = prirucnik.prompt_section(mesto)
        if not odeljak:
            self.stdout.write(self.style.ERROR(f"{mesto}: nema aktivnih pravila."))
            return
        self.stdout.write(odeljak)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{len(odeljak)} znakova od {prirucnik.PRIRUCNIK_BUDGET_CHARS}"))

    def _upisi(self, mesto: str, actor: str) -> None:
        jezgro = JEZGRA.get(mesto)
        if jezgro is None:
            raise CommandError(
                f"Za mesto {mesto!r} nije napisano jezgro; poznata: {sorted(JEZGRA)}. "
                "Jezgro piše čovek i odobrava ga Slobodan (ADR-0060 §5).")
        br = prirucnik.upisi(mesto, jezgro, actor=actor)
        self.stdout.write(self.style.SUCCESS(
            f"upisano {br['upisano']}, izmenjeno {br['izmenjeno']}, "
            f"netaknuto {br['netaknuto']}"))
        self.stdout.write(f"Od sada idu u svaki prompt za pisanje koda na mestu {mesto}.")

    def _ugasi(self, mesto: str, kljuc: str, zasto: str, actor: str) -> None:
        if not zasto.strip():
            raise CommandError("Gašenje pravila traži `--zasto`.")
        try:
            red = prirucnik.ugasi(mesto, kljuc, razlog=zasto, actor=actor)
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(f"ugašeno {mesto}/{red.key}"))
        self.stdout.write("Ostaje upisano sa razlogom; iz prompta izlazi odmah.")
