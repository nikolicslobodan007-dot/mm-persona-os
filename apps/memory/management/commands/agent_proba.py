"""manage.py agent_proba — pokaži kako persona KORISTI sabrane veštine u radu.

Daj temu → persona izgradi kontekst (semantički izvuče SLOBODNA veštine iz baze
znanja, ADR-0120) i napravi nacrt kroz živ Gateway (ADR-0009). Pokazuje:
  1) koje je veštine izvukla (dokaz da sakupljač hrani agenta),
  2) nacrt koji je napravila,
  3) rutu i trošak.

NE čuva sadržaj i ne ide na odobrenje — showcase celog lanca, ne objava.

    python manage.py agent_proba --persona P-00001 --tema "AI agenti u prodaji"
    python manage.py agent_proba --tema "montaža videa" --pun-kontekst
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.context import bind
from apps.content.service import _system_prompt, operator_run
from apps.llm_gateway import gateway
from apps.memory import context as memory_context
from apps.memory.models import KnowledgeFact
from apps.personas.models import Persona
from common import enums as E


class Command(BaseCommand):
    help = "Showcase: persona koristi sabrane veštine → nacrt kroz živ Gateway."

    def add_arguments(self, p):
        p.add_argument("--persona", default="P-00001", help="public_id persone.")
        p.add_argument("--tema", required=True, help="Tema zadatka za agenta.")
        p.add_argument("--actor", default="user:slobodan", help="Mora početi sa 'user:'.")
        p.add_argument("--pun-kontekst", action="store_true",
                       help="Ispiši i ceo kontekst (prompt) koji je agent dobio.")

    def handle(self, *args, **o):
        if not o["actor"].startswith("user:"):
            raise CommandError("--actor mora da počne sa 'user:'.")
        try:
            persona = Persona.objects.get(public_id=o["persona"])
        except Persona.DoesNotExist as e:
            raise CommandError(f"Nema persone: {o['persona']}") from e

        tema = o["tema"]
        now = timezone.now()
        with bind(actor_id=o["actor"]):
            run = operator_run(persona, now)
            pack = memory_context.build(
                persona, run, E.RetrievalProfile.CONTENT_CREATION, query=tema, now=now)

            self.stdout.write(self.style.MIGRATE_HEADING(
                f"# {persona.public_id} ({persona.display_name}) · tema: {tema}"))

            # 1) Izvučene veštine — dokaz da sabrano znanje hrani agenta
            ids = pack.record.vestina_ids or []
            facts = {str(f.id): f for f in KnowledgeFact.objects
                     .filter(id__in=ids).select_related("source")}
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n## Izvučene veštine ({len(ids)}):"))
            for i in ids:
                f = facts.get(i)
                if f:
                    izvor = f.source.title if f.source else "?"
                    self.stdout.write(f"- {f.subject}  ⟵ {izvor}")
            if not ids:
                self.stdout.write("(nijedna — baza nema SLOBODNA veštinu za ovu temu)")

            if o["pun_kontekst"]:
                self.stdout.write(self.style.MIGRATE_HEADING("\n## Pun kontekst (prompt):"))
                self.stdout.write(pack.text)

            # 2) Nacrt kroz živ Gateway
            from apps.content.lessons import prompt_section
            rules = prompt_section(persona)
            gen = gateway.generate(
                E.LLMPurpose.CONTENT_DRAFT, _system_prompt(persona),
                f"{pack.text}\n\n" + (f"{rules}\n\n" if rules else "")
                + f"## zadatak\nNapiši kratku objavu na temu: {tema}.",
                persona=persona, run=run, context_pack=pack.record,
                brief={"topic": tema, "facts": [], "language": persona.primary_locale})

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n## Nacrt ({gen.provider}, {gen.amount_eur_cents}¢):"))
        self.stdout.write(gen.text)
        if gen.fallbacks:
            self.stdout.write(f"\n(fallback rute: {gen.fallbacks})")
