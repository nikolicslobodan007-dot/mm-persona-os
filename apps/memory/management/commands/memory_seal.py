"""Pečaćenje memorije iz komandne linije. ADR-0020.

    manage.py memory_seal --show                 (šta bi se zapečatilo)
    manage.py memory_seal --persona P-00001      (samo jedan agent)
    manage.py memory_seal                        (cela kaskada: agent → sektor → firma)

Pečaćenje ne zove model i ne košta ništa: sažetak je sastavljen od podataka.
Izvori se arhiviraju, ne brišu, i svaki ima vezu do sažetka.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.memory import sealing
from apps.memory.models import MemoryItem
from apps.personas.models import Persona
from common import enums as E


class Command(BaseCommand):
    help = "Sažima memoriju u nivoe i gradi znanje sektora i firme."

    def add_arguments(self, parser):
        parser.add_argument("--persona", default="")
        parser.add_argument("--actor", default="service:memory")
        parser.add_argument("--show", action="store_true",
                            help="Samo prikaz: koje teme su prepune.")
        parser.add_argument("--threshold", type=int, default=0,
                            help="Prag za jedno pokretanje (podrazumevano 12).")

    def handle(self, *args, persona, actor, show, threshold, **opts):
        people = Persona.objects.exclude(status=E.PersonaStatus.ARCHIVED.value)
        if persona:
            people = people.filter(public_id=persona)
            if not people.exists():
                raise CommandError(f"Persona {persona} ne postoji.")

        if show:
            for p in people:
                qs = MemoryItem.objects.filter(persona=p, scope=E.MemoryScope.PERSONA.value,
                                               status=E.MemoryStatus.ACTIVE.value)
                rows = sorted(sealing._buckets(qs, 0).items(), key=lambda x: -len(x[1]))
                self.stdout.write(f"{p.public_id} · {p.display_name}")
                for topic, items in rows[:10]:
                    mark = "→ peča se" if len(items) >= sealing.SEAL_AT_PERSONA else ""
                    self.stdout.write(f"  {len(items):4}  {topic:40} {mark}")
                if not rows:
                    self.stdout.write("  (nema zapisa)")
                self.stdout.write(f"  vidi: {sealing.counts(p)}")
            return

        with bind(actor_id=actor):
            if persona:
                made = sealing.seal_persona(people.first(),
                                            threshold=threshold or None)
                self.stdout.write(self.style.SUCCESS(f"Sažetaka: {len(made)}"))
                return
            stats = sealing.seal_all()
        self.stdout.write(self.style.SUCCESS(
            f"Agent: {stats['agent']} · sektor: {stats['sektor']} · firma: {stats['firma']}"))
