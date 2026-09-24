"""Planovi agenta iz komandne linije. ADR-0021.

    manage.py plan --persona P-00001            (spisak planova i koraka)
    manage.py plan --handlers                   (koji obrađivači postoje)
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.orchestration import plans
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Prikazuje planove i njihove korake."

    def add_arguments(self, parser):
        parser.add_argument("--persona", default="")
        parser.add_argument("--handlers", action="store_true")

    def handle(self, *args, persona, handlers, **opts):
        if handlers:
            for name in plans.registered():
                self.stdout.write(name)
            return
        if not persona:
            raise CommandError("Zadaj --persona ili --handlers.")
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"Persona {persona} ne postoji.")
        found = plans.active_for(p, limit=20)
        if not found:
            self.stdout.write("Nema planova.")
            return
        for pl in found:
            self.stdout.write(f"\n{pl.public_id}  {pl.status}  {pl.created_at:%d.%m %H:%M}")
            self.stdout.write(f"  cilj: {pl.goal}")
            parent = plans.parent_of(pl)
            if parent is not None:
                self.stdout.write(f"  zadao: {parent.persona.public_id} ({parent.public_id})")
            for s in pl.steps.order_by("sequence"):
                out = s.output_json or {}
                if out.get("waiting_for_plan"):
                    extra = f"→ {out.get('worker', '')} {out['waiting_for_plan']}"
                else:
                    extra = out.get("waiting_for") or out.get("reason", "")
                self.stdout.write(f"  {s.sequence}. {s.description:44} {s.status:8} {extra}")
