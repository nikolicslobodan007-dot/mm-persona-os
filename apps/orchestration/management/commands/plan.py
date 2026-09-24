"""Planovi agenta iz komandne linije. ADR-0021.

    manage.py plan --persona P-00001            (spisak planova i koraka)
    manage.py plan --handlers                   (koji obrađivači postoje)

Zadavanje posla izvršiocu (ADR-0022/0024):

    manage.py plan --persona P-00001 --zadaj P-00002 --tema "Rokovi u B2B"

Šef dobija plan od dva koraka: zadaj → zaključi. Izvršilac dobija svoj plan
sa nacrtom. Šefov korak stoji dok izvršilac ne završi.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.orchestration import plans
from apps.personas import org
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Prikazuje planove i njihove korake."

    def add_arguments(self, parser):
        parser.add_argument("--persona", default="")
        parser.add_argument("--handlers", action="store_true")
        parser.add_argument("--zadaj", default="", help="Public ID izvršioca.")
        parser.add_argument("--tema", default="", help="Tema nacrta za izvršioca.")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, persona, handlers, zadaj, tema, actor, **opts):
        if handlers:
            for name in plans.registered():
                self.stdout.write(name)
            return
        if not persona:
            raise CommandError("Zadaj --persona ili --handlers.")
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"Persona {persona} ne postoji.")
        if zadaj:
            return self._zadaj(p, zadaj, tema, actor)
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

    def _zadaj(self, boss: Persona, worker_id: str, tema: str, actor: str) -> None:
        """Šef zadaje posao izvršiocu — pravi put, kroz plan (ADR-0022)."""
        worker = Persona.objects.filter(public_id=worker_id).first()
        if worker is None:
            raise CommandError(f"Persona {worker_id} ne postoji.")
        if why := org.can_delegate(boss, worker):
            raise CommandError(why)
        if not tema.strip():
            raise CommandError("Zadaj --tema: izvršilac mora da zna o čemu piše.")
        with bind(actor_id=actor):
            plan = plans.start(boss, f"Zadatak: {tema}", [
                {"handler": "org.delegate",
                 "description": f"Zadaj: {worker.display_name}",
                 "input": {"to": worker.public_id, "goal": tema,
                           "steps": [{"handler": "content.draft",
                                      "description": "Napiši nacrt",
                                      "input": {"tema": tema}}]}},
                {"handler": "plan.note", "description": "Preuzmi gotov posao",
                 "input": {"note": f"Nacrt preuzet od {worker.public_id}."}},
            ], actor=actor)
            plans.advance(plan)
        plan.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f"{plan.public_id}  {plan.status} — {plans.summary(plan)}"))
        for s in plan.steps.order_by("sequence"):
            self.stdout.write(f"  {s.sequence}. {s.description:36} {s.status}")
        child = plans.AgentPlan.objects.filter(persona=worker).order_by(
            "-created_at").first()
        if child is not None:
            self.stdout.write(f"\n  izvršilac: {child.public_id}  {child.status}")
            for s in child.steps.order_by("sequence"):
                out = s.output_json or {}
                self.stdout.write(f"  {s.sequence}. {s.description:36} {s.status}")
                if model := out.get("model"):
                    self.stdout.write(f"     model: {model}")
                    if model.startswith("local/"):
                        self.stdout.write(self.style.WARNING(
                            "     ⚠ pisao je lokalni šablon, ne model — "
                            "izvršilac nema ključ ili ruta za ovu svrhu nije uključena."))
                if tekst := out.get("tekst"):
                    self.stdout.write(f"     {tekst[:300]}")
