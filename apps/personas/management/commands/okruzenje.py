"""Okruženje agenta: jedini put iz simulacije u živo i nazad. ADR-0100.

    manage.py okruzenje --spisak
    manage.py okruzenje --persona P-00012 --na CONTROLLED_LIVE \\
                        --razlog "čita javne izvore za nalaze" --actor user:slobodan

Okruženje samo po sebi **ne daje nijednu dozvolu**. Ono uklanja jedan od
uslova za živo izvršenje; poverenje, odobrenja, kvote i oba prekidača iz
ADR-0099 važe nepromenjeno.

`--razlog` i `--actor` su obavezni i nemaju podrazumevanu vrednost: razlog
koji se podrazumeva nije razlog. Upis u audit je svrha ove komande.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api import audit
from api.context import bind
from apps.personas.models import Persona
from common import enums as E

#: ADR-0100 tačka 4 — u živo samo agent koji stvarno radi.
ZA_ZIVO = frozenset({E.PersonaStatus.READY.value, E.PersonaStatus.ACTIVE.value})

#: Mora da se poklapa sa `_LIVE_ENVIRONMENTS` u `apps/policy/gateway.py`.
ZIVA = frozenset({E.RuntimeEnvironment.CONTROLLED_LIVE.value,
                  E.RuntimeEnvironment.LIVE.value})


class Command(BaseCommand):
    help = "Menja okruzenje agenta (ADR-0100). Upisuje ko, zasto i iz cega u sta."

    def add_arguments(self, parser):
        parser.add_argument("--spisak", action="store_true",
                            help="Ko je u kom okruženju.")
        parser.add_argument("--persona", default="", help="P-…")
        parser.add_argument("--na", default="",
                            help=f"Jedno od: {', '.join(E.RuntimeEnvironment.values())}")
        parser.add_argument("--razlog", default="", help="Obavezno. Ostaje u auditu.")
        parser.add_argument("--actor", default="", help="Obavezno, npr. user:slobodan")

    def handle(self, *args, spisak, persona, na, razlog, actor, **opts):
        if spisak:
            for p in Persona.objects.order_by("runtime_environment", "public_id"):
                ziv = "ŽIVO" if p.runtime_environment in ZIVA else "    "
                self.stdout.write(
                    f"{ziv}  {p.public_id}  {p.runtime_environment:16} "
                    f"{p.status:10} {p.display_name}")
            return

        if not persona or not na:
            raise CommandError("Treba --persona i --na (ili --spisak).")
        if not razlog.strip():
            raise CommandError("--razlog je obavezan (ADR-0100 tačka 2).")
        if not actor.startswith("user:"):
            raise CommandError("--actor mora biti čovek (user:…). Agent ne pušta sam sebe.")
        if na not in E.RuntimeEnvironment.values():
            raise CommandError(f"Nepoznato okruženje {na!r}. "
                               f"Postoje: {', '.join(E.RuntimeEnvironment.values())}")

        with transaction.atomic():
            p = Persona.objects.select_for_update().filter(public_id=persona).first()
            if p is None:
                raise CommandError(f"Persona {persona} ne postoji.")
            staro = p.runtime_environment
            if staro == na:
                self.stdout.write(f"{p.public_id} je već u {na} — ništa nije promenjeno.")
                return
            if na in ZIVA and p.status not in ZA_ZIVO:
                raise CommandError(
                    f"{p.public_id} je {p.status}; u živo ide samo "
                    f"{' ili '.join(sorted(ZA_ZIVO))} (ADR-0100 tačka 4).")

            Persona.objects.filter(pk=p.pk).update(runtime_environment=na)
            p.refresh_from_db()
            with bind(actor_id=actor):
                audit.record(
                    "persona.environment.changed",
                    severity=(E.AuditSeverity.WARNING if na in ZIVA
                              else E.AuditSeverity.INFO),
                    persona=p,
                    before={"runtime_environment": staro},
                    after={"runtime_environment": na},
                    details={"actor": actor, "razlog": razlog.strip(),
                             "zivo": na in ZIVA},
                )

        strelica = "→ ŽIVO" if na in ZIVA else "→ zatvoreno"
        self.stdout.write(self.style.SUCCESS(
            f"{p.public_id} · {p.display_name}: {staro} → {na}  {strelica}"))
        self.stdout.write(f"  razlog: {razlog.strip()}")
        self.stdout.write("  Okruženje ne daje nijednu dozvolu samo po sebi (ADR-0100).")
