"""Čija je greška što je zakrpa odbijena. ADR-0053.

    manage.py krivica --zadatak TSK-... --spisak
    manage.py krivica --zakrpa 0bb3ea49 --kome SISTEM \\
        --zasto "Naš parser je tražio `diff --git`, ADR-0048."

`ucinak` je do ovog ADR-a brojao odbijanja i ćutao o uzroku, pa su naši kvarovi
stajali kao agentov promašaj. Ova komanda je jedini put da se to ispravi — i
namerno je ručna: presudu o tuđem radu donosi čovek, ne mašina.

Zakrpa se po **početku identifikatora** pogađa, kao commit u `git`-u.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.orchestration import zadaci, zakrpa
from apps.orchestration.models import CodeTask, TaskPatch
from common import enums as E

#: Koliko znakova identifikatora je dovoljno da se zakrpa pogodi.
PREFIKS = 8


class Command(BaseCommand):
    help = "Pripisuje krivicu za odbijenu zakrpu (ADR-0053)."

    def add_arguments(self, parser):
        parser.add_argument("--zadatak", default="", help="TSK-… uz --spisak")
        parser.add_argument("--spisak", action="store_true")
        parser.add_argument("--zakrpa", default="", help="Početak identifikatora.")
        parser.add_argument("--kome", default="", choices=E.PatchFault.values())
        parser.add_argument("--zasto", default="")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, zadatak, spisak, zakrpa: str, kome, zasto, actor, **opts):
        if not actor.startswith("user:"):
            raise CommandError(
                "Krivicu pripisuje čovek; `--actor` mora da počne sa `user:`.")
        if spisak:
            if not zadatak:
                raise CommandError("Uz `--spisak` ide `--zadatak`.")
            return self._spisak(zadatak)
        if not (zakrpa and kome):
            raise CommandError("Treba `--zakrpa` i `--kome` (ili `--spisak`).")
        if not zasto.strip():
            raise CommandError("Uz `--kome` ide `--zasto` sa razlogom.")
        self._pripisi(zakrpa, kome, zasto, actor)

    # ------------------------------------------------------------------ spisak

    def _spisak(self, task_id: str) -> None:
        zad = CodeTask.objects.filter(public_id=task_id).first()
        if zad is None:
            raise CommandError(f"Zadatak {task_id} ne postoji.")
        redovi = zad.patches.filter(status=E.PatchStatus.REJECTED.value) \
                            .order_by("created_at")
        if not redovi:
            self.stdout.write(f"{zad.public_id}: nema odbijenih zakrpa.")
            return
        for p in redovi:
            kratak = str(p.pk)[:PREFIKS]
            boja = (lambda s: s) if p.fault == E.PatchFault.AGENT.value \
                else self.style.SUCCESS
            self.stdout.write(
                f"{kratak}  {p.created_at.strftime('%d.%m %H:%M')}  "
                f"{boja(f'{p.fault:7}')} {p.cost_eur_cents:>3} c  "
                f"{(p.reason or '')[:90]}")
            if p.fault_reason:
                self.stdout.write(f"          → {p.fault_reason[:110]}")

    # ---------------------------------------------------------------- pripisi

    def _pripisi(self, prefiks: str, kome: str, zasto: str, actor: str) -> None:
        pogodak = [p for p in TaskPatch.objects.filter(
            status=E.PatchStatus.REJECTED.value) if str(p.pk).startswith(prefiks)]
        if not pogodak:
            raise CommandError(
                f"Nijedna odbijena zakrpa ne počinje sa {prefiks!r}.")
        if len(pogodak) > 1:
            raise CommandError(
                f"{prefiks!r} pogađa {len(pogodak)} zakrpa — daj više znakova.")
        red = pogodak[0]
        pre = red.fault
        try:
            with bind(actor_id=actor):
                zakrpa.pripisi_krivicu(red, kome, actor=actor, razlog=zasto)
        except zadaci.TaskError as e:
            raise CommandError(f"{e.code}: {e}") from e
        self.stdout.write(self.style.SUCCESS(
            f"{str(red.pk)[:PREFIKS]}  {pre} → {red.fault}"))
        self.stdout.write(f"  razlog: {red.fault_reason[:140]}")
