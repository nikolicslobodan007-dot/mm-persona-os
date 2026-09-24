"""Zadaci programerskog sektora. ADR-0035.

    manage.py zadatak --novi --naslov "..." --zasto "..." \\
        --putanje apps/content,tests/test_content.py --adr 0024 --izvrsilac P-00027

    manage.py zadatak --spisak
    manage.py zadatak --zadatak TSK-... (stanje, kapije, nalazi)
    manage.py zadatak --zadatak TSK-... --sme apps/content/steps.py
    manage.py zadatak --zadatak TSK-... --kapija pytest --prosla
    manage.py zadatak --zadatak TSK-... --zavrsi --commit 9f65d41
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.orchestration import zadaci
from apps.orchestration.models import CodeTask
from apps.personas.models import Persona


def _persona(public_id: str) -> Persona:
    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise CommandError(f"Persona {public_id} ne postoji.")
    return p


class Command(BaseCommand):
    help = "Zadaci: pravljenje, dodela, kapije, nalazi, zatvaranje (ADR-0035)."

    def add_arguments(self, parser):
        parser.add_argument("--novi", action="store_true")
        parser.add_argument("--naslov", default="")
        parser.add_argument("--zasto", default="")
        parser.add_argument("--putanje", default="", help="Zarezom razdvojeni prefiksi.")
        parser.add_argument("--kapije", default="", help="Zarezom; podrazumevano sve mašinske.")
        parser.add_argument("--adr", default="")
        parser.add_argument("--izvrsilac", default="")
        parser.add_argument("--recenzent", default="")
        parser.add_argument("--spisak", action="store_true")
        parser.add_argument("--zadatak", default="", help="TSK-...")
        parser.add_argument("--sme", default="", help="Putanja koju treba proveriti.")
        parser.add_argument("--kapija", default="")
        parser.add_argument("--prosla", action="store_true")
        parser.add_argument("--pala", action="store_true")
        parser.add_argument("--ispis", default="")
        parser.add_argument("--zavrsi", action="store_true")
        parser.add_argument("--commit", default="")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, novi, naslov, zasto, putanje, kapije, adr, izvrsilac,
               recenzent, spisak, zadatak, sme, kapija, prosla, pala, ispis,
               zavrsi, commit, actor, **opts):
        with bind(actor_id=actor):
            try:
                self._radi(novi, naslov, zasto, putanje, kapije, adr, izvrsilac,
                           recenzent, spisak, zadatak, sme, kapija, prosla, pala,
                           ispis, zavrsi, commit)
            except zadaci.TaskError as e:
                raise CommandError(f"{e.code}: {e}") from e

    def _radi(self, novi, naslov, zasto, putanje, kapije, adr, izvrsilac, recenzent,
              spisak, zadatak, sme, kapija, prosla, pala, ispis, zavrsi, commit):
        if novi:
            z = zadaci.create(
                title=naslov, why=zasto, adr=adr,
                allowed_paths=[p for p in putanje.split(",") if p.strip()],
                gates=[g.strip() for g in kapije.split(",") if g.strip()] or None,
                assignee=_persona(izvrsilac) if izvrsilac else None,
                reviewer=_persona(recenzent) if recenzent else None,
            )
            self.stdout.write(self.style.SUCCESS(f"{z.public_id} · {z.title}"))
            self.stdout.write(f"  putanje: {', '.join(z.allowed_paths)}")
            self.stdout.write(f"  kapije:  {', '.join(z.required_gates)}")
            return

        if spisak:
            redovi = CodeTask.objects.order_by("-created_at")[:30]
            if not redovi:
                self.stdout.write("Nema nijednog zadatka.")
                return
            for z in redovi:
                ko = z.assignee.public_id if z.assignee_id else "—"
                self.stdout.write(f"{z.public_id}  {z.status:12} {ko:9} {z.title[:50]}")
            return

        if not zadatak:
            raise CommandError("Treba --zadatak, --spisak ili --novi.")
        z = CodeTask.objects.filter(public_id=zadatak).first()
        if z is None:
            raise CommandError(f"Zadatak {zadatak} ne postoji.")

        if izvrsilac:
            zadaci.assign(z, assignee=_persona(izvrsilac),
                          reviewer=_persona(recenzent) if recenzent else None)
            self.stdout.write(self.style.SUCCESS(
                f"{z.public_id} → {z.assignee.public_id}"))
            return

        if sme:
            razlog = zadaci.may_touch(z, sme)
            self.stdout.write(f"{sme}: " + (
                self.style.ERROR(f"ne sme — {razlog}") if razlog
                else self.style.SUCCESS("sme")))
            return

        if kapija:
            if prosla == pala:
                raise CommandError("Treba tačno jedno: --prosla ili --pala.")
            zadaci.record_gate(z, kapija, prosla, detail=ispis, commit_sha=commit)
            self.stdout.write(
                (self.style.SUCCESS if prosla else self.style.ERROR)(
                    f"{z.public_id} · {kapija} · {'prošla' if prosla else 'pala'}"))
            return

        if zavrsi:
            zadaci.finish(z, commit_sha=commit)
            self.stdout.write(self.style.SUCCESS(
                f"{z.public_id} gotov ({z.commit_sha or 'bez commita'})"))
            return

        self.stdout.write(f"{z.public_id} · {z.status} · {z.title}")
        self.stdout.write(f"  zašto:   {z.why}")
        if z.adr:
            self.stdout.write(f"  ADR:     {z.adr}")
        self.stdout.write(f"  putanje: {', '.join(z.allowed_paths)}")
        self.stdout.write("  kapije:")
        for g, ok in zadaci.gate_report(z).items():
            oznaka = {True: "zelena", False: "pala", None: "nije vrtena"}[ok]
            stil = self.style.SUCCESS if ok else (
                self.style.WARNING if ok is None else self.style.ERROR)
            self.stdout.write(f"    {g:14} {stil(oznaka)}")
        nalazi = z.findings.order_by("severity", "file")
        if nalazi:
            self.stdout.write("  nalazi:")
            for n in nalazi:
                self.stdout.write(
                    f"    [{n.severity:7}] {n.file}:{n.line or '-'} "
                    f"({n.status}) {n.claim[:60]}")
        blokade = zadaci.blocking_findings(z).count()
        if blokade:
            self.stdout.write(self.style.ERROR(
                f"  {blokade} otvoren(ih) BLOCKER nalaz(a) — zadatak se ne zatvara."))
