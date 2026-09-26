"""Nalaz koji piše čovek. ADR-0045.

    manage.py nalaz --zadatak TSK-... --spisak
    manage.py nalaz --zadatak TSK-... --fajl apps/content/lessons.py --linija 131 \\
        --tvrdnja "Odseca pouke bez ijedne reči da je odsekao." --tezina BLOCKER
    manage.py nalaz --zadatak TSK-... --izmeni 1a2b3c4d --tvrdnja "ispravljen tekst"
    manage.py nalaz --zadatak TSK-... --zatvori 1a2b3c4d --kako FIXED

`manage.py recenzija` uvozi ono što je našao alat. Ovo je druga strana: ADR-0036
§2 kaže da `BLOCKER` postavlja isključivo čovek — a do ovog ADR-a čovek nije imao
čime. Jedina težina koja zaustavlja zadatak bila je nedostupna onome ko je jedini
sme dati.

Nalaz se zatvara po **početku identifikatora**, kao commit u `git`-u: ceo UUID se
ne prepisuje rukom (ADR-0033, isto pravilo kao za ULID).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.orchestration import zadaci
from apps.orchestration.models import CodeTask, ReviewFinding
from common import enums as E

#: Koliko znakova identifikatora je dovoljno da se nalaz pogodi.
PREFIKS = 8


class Command(BaseCommand):
    help = "Nalaz recenzenta-čoveka: upis, spisak, zatvaranje (ADR-0045)."

    def add_arguments(self, parser):
        parser.add_argument("--zadatak", required=True, help="TSK-...")
        parser.add_argument("--spisak", action="store_true")
        parser.add_argument("--fajl", default="")
        parser.add_argument("--linija", type=int, default=None)
        parser.add_argument("--tvrdnja", default="")
        parser.add_argument("--tezina", default=E.FindingSeverity.MAJOR.value,
                            choices=E.FindingSeverity.values())
        parser.add_argument("--izmeni", default="",
                            help="Početak identifikatora — ispravlja tvrdnju.")
        parser.add_argument("--zatvori", default="", help="Početak identifikatora nalaza.")
        parser.add_argument("--kako", default=E.FindingStatus.FIXED.value,
                            choices=[s for s in E.FindingStatus.values()
                                     if s != E.FindingStatus.OPEN.value])
        parser.add_argument("--napomena", default="")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, zadatak, spisak, fajl, linija, tvrdnja, tezina,
               izmeni, zatvori, kako, napomena, actor, **opts):
        z = CodeTask.objects.filter(public_id=zadatak).first()
        if z is None:
            raise CommandError(f"Zadatak {zadatak} ne postoji.")

        if not actor.startswith("user:"):
            raise CommandError(
                "Ovu komandu pokreće čovek; `--actor` mora da počne sa `user:` "
                "(ADR-0036 §2).")

        with bind(actor_id=actor):
            try:
                if spisak:
                    self._spisak(z)
                elif izmeni:
                    self._izmeni(z, izmeni, tvrdnja, actor)
                elif zatvori:
                    self._zatvori(z, zatvori, kako, napomena, actor)
                else:
                    self._upisi(z, fajl, linija, tvrdnja, tezina)
            except zadaci.TaskError as e:
                raise CommandError(f"{e.code}: {e}") from e

    # ------------------------------------------------------------------ spisak

    def _spisak(self, z: CodeTask) -> None:
        redovi = z.findings.order_by("status", "-created_at")
        if not redovi:
            self.stdout.write(f"{z.public_id}: nema nijedan nalaz.")
            return
        for n in redovi:
            kratak = str(n.pk)[:PREFIKS]
            boja = (self.style.ERROR if n.severity == E.FindingSeverity.BLOCKER.value
                    and n.status == E.FindingStatus.OPEN.value else self.style.SUCCESS
                    if n.status != E.FindingStatus.OPEN.value else (lambda s: s))
            self.stdout.write(
                f"{kratak}  {boja(f'{n.severity:8}')} {n.status:8} "
                f"{n.source:16} {n.file}:{n.line or '-'}")
            self.stdout.write(f"          {n.claim[:160]}")
        otvoreni = z.findings.filter(severity=E.FindingSeverity.BLOCKER.value,
                                     status=E.FindingStatus.OPEN.value).count()
        if otvoreni:
            self.stdout.write(self.style.ERROR(
                f"\nOtvorenih BLOCKER nalaza: {otvoreni}. Zadatak se ne zatvara i "
                f"grana se ne otvara dok stoje (ADR-0035 §3, ADR-0043)."))

    # ------------------------------------------------------------------- upis

    def _upisi(self, z: CodeTask, fajl: str, linija, tvrdnja: str, tezina: str) -> None:
        if not (fajl.strip() and tvrdnja.strip()):
            raise CommandError("Treba `--fajl` i `--tvrdnja` (ili `--spisak`).")
        n = zadaci.add_finding(z, reviewer=None, file=fajl, claim=tvrdnja,
                               severity=tezina, line=linija,
                               source=zadaci.IZVOR_COVEK)
        self.stdout.write(self.style.SUCCESS(
            f"{str(n.pk)[:PREFIKS]}  {n.severity}  {n.file}:{n.line or '-'}"))
        if tezina == E.FindingSeverity.BLOCKER.value:
            self.stdout.write("Zadatak od sada ne može da se zatvori niti da otvori "
                              "granu dok ovaj nalaz stoji.")

    # ----------------------------------------------------------------- ispravka

    def _izmeni(self, z: CodeTask, prefiks: str, tvrdnja: str, actor: str) -> None:
        if not tvrdnja.strip():
            raise CommandError("Uz `--izmeni` ide `--tvrdnja` sa novim tekstom.")
        n = self._nadji(z, prefiks)
        staro = n.claim
        zadaci.amend_finding(n, tvrdnja, actor=actor)
        self.stdout.write(f"{str(n.pk)[:PREFIKS]}  {n.severity}  tvrdnja ispravljena")
        self.stdout.write(f"  pre:   {staro[:120]}")
        self.stdout.write(f"  posle: {n.claim[:120]}")

    # -------------------------------------------------------------- zatvaranje

    def _nadji(self, z: CodeTask, prefiks: str) -> ReviewFinding:
        """Nalaz po početku identifikatora. Dvosmislen prefiks se odbija, ne pogađa."""
        pogodak = [n for n in z.findings.all() if str(n.pk).startswith(prefiks)]
        if not pogodak:
            raise CommandError(f"Nijedan nalaz ovog zadatka ne počinje sa {prefiks!r}.")
        if len(pogodak) > 1:
            raise CommandError(
                f"{prefiks!r} pogađa {len(pogodak)} nalaza — daj više znakova.")
        return pogodak[0]

    def _zatvori(self, z: CodeTask, prefiks: str, kako: str, napomena: str,
                 actor: str) -> None:
        n = self._nadji(z, prefiks)
        zadaci.close_finding(n, kako, actor=actor, note=napomena)
        self.stdout.write(self.style.SUCCESS(
            f"{str(n.pk)[:PREFIKS]}  {n.severity}  → {kako}"))
