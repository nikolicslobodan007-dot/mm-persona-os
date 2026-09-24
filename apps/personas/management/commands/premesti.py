"""Premeštaj agenta na drugo radno mesto. ADR-0023.

    manage.py premesti --persona P-00001 --mesto SEF-MKT

Stari raspored se **zatvara, ne briše** (ADR-0017) — istorija ostaje. Ako je
novo mesto popunjeno, premeštaj se odbija; prvo se oslobodi mesto.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.personas import org
from apps.personas.models import Persona, Position


class Command(BaseCommand):
    help = "Premešta agenta na drugo radno mesto."

    def add_arguments(self, parser):
        parser.add_argument("--persona", required=True)
        parser.add_argument("--mesto", required=True)
        parser.add_argument("--actor", default="user:slobodan")
        parser.add_argument("--razlog", default="")

    def handle(self, *args, persona, mesto, actor, razlog, **opts):
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"Persona {persona} ne postoji.")
        position = Position.objects.filter(code=mesto).select_related(
            "department").first()
        if position is None:
            raise CommandError(f"Radno mesto „{mesto}” ne postoji.")
        staro = org.position_of(p)
        try:
            with bind(actor_id=actor):
                org.assign(p, position, actor=actor, note=razlog)
        except org.OrgError as e:
            raise CommandError(str(e)) from e

        boss = org.manager_of(p)
        self.stdout.write(self.style.SUCCESS(
            f"{p.public_id} — {staro.code if staro else 'bez mesta'} → "
            f"{position.code} ({position.department.name} / {position.title})."))
        self.stdout.write(f"  odgovara: {boss.display_name if boss else 'čoveku'}")
        podredjeni = org.subordinates(p)
        self.stdout.write("  njemu odgovaraju: " + (
            ", ".join(x.display_name for x in podredjeni) if podredjeni else "niko"))
