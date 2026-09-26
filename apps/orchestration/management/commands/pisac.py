"""Model piše zakrpu. ADR-0044.

    manage.py pisac --zadatak TSK-...              (jedan pokušaj)
    manage.py pisac --zadatak TSK-... --zasto      (samo: sme li i zašto ne)
    manage.py pisac --sve                          (po jedan pokušaj gde sme)
    manage.py pisac --zadatak TSK-... --plafon 100 --najvise 5

Jedan poziv = jedan pokušaj. Kapije vrti poslušnik, van aplikacije, pa se
povratna informacija vraća kroz brif pri sledećem pokušaju (ADR-0044).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.orchestration import pisac
from apps.orchestration.models import CodeTask
from apps.orchestration.zadaci import TaskError
from common import enums as E


class Command(BaseCommand):
    help = "Model piše zakrpu za zadatak (ADR-0044)."

    def add_arguments(self, parser):
        parser.add_argument("--zadatak", default="", help="TSK-...")
        parser.add_argument("--sve", action="store_true")
        parser.add_argument("--zasto", action="store_true",
                            help="Samo ispiši zašto se pokušaj ne pravi.")
        parser.add_argument("--plafon", type=int, default=pisac.PLAFON_CENTI)
        parser.add_argument("--najvise", type=int, default=pisac.NAJVISE_POKUSAJA)
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, zadatak, sve, zasto, plafon, najvise, actor, **opts):
        if bool(zadatak) == bool(sve):
            raise CommandError("Treba tačno jedno: --zadatak ili --sve.")

        if zadatak:
            z = CodeTask.objects.filter(public_id=zadatak).first()
            if z is None:
                raise CommandError(f"Zadatak {zadatak} ne postoji.")
            redovi = [z]
        else:
            redovi = list(CodeTask.objects.exclude(
                status__in=[E.TaskStatus.DONE.value, E.TaskStatus.CANCELLED.value]
            ).exclude(assignee=None).order_by("created_at"))

        if not redovi:
            self.stdout.write("Nema otvorenog zadatka sa izvršiocem.")
            return

        with bind(actor_id=actor):
            for z in redovi:
                self._jedan(z, zasto, plafon, najvise)

    def _jedan(self, z, samo_zasto: bool, plafon: int, najvise: int) -> None:
        kocnica = pisac.zasto_ne(z, plafon_centi=plafon, najvise=najvise)
        glava = f"{z.public_id} · {z.title[:50]}"
        if kocnica:
            self.stdout.write(f"{glava}\n  {self.style.WARNING('ne piše se')} — {kocnica}")
            return
        if samo_zasto:
            self.stdout.write(f"{glava}\n  {self.style.SUCCESS('sme')}")
            return

        try:
            ishod = pisac.pokusaj(z, plafon_centi=plafon, najvise=najvise)
        except TaskError as e:
            self.stdout.write(f"{glava}\n  {self.style.ERROR(str(e))}")
            return

        boja = self.style.SUCCESS if ishod.napisano else self.style.ERROR
        self.stdout.write(
            f"{glava}\n"
            f"  {boja(ishod.status or 'bez zakrpe')}"
            f"  model: {ishod.model or '—'}"
            f"  cena: {ishod.cena_centi} c"
            f"  ukupno: {ishod.potroseno_ukupno}/{plafon} c"
            f"  pokušaj: {ishod.pokusaja}/{najvise}")
        if ishod.putanje:
            self.stdout.write(f"  putanje: {', '.join(ishod.putanje)}")
        if ishod.razlog:
            self.stdout.write(f"  razlog:  {ishod.razlog[:300]}")
        if ishod.napisano:
            self.stdout.write("  zakrpa je u redu — poslušnik je uzima na sledećem prolazu.")
