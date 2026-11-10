"""manage.py agent_zadatak — persona pravi BOGATIJI radni artefakt (stavka 2).

Bira vrstu zadatka (battlecard, outreach, plan-naloga, objava), sastavi kontekst
upitom te vrste (ADR-0131 digne pravu veštinu u sloj sa koracima) i pusti kroz
živ Gateway. Showcase: ispisuje artefakt; NE čuva (persistencija je sledeći sloj).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.context import bind
from apps.content import zadaci
from apps.content.service import _system_prompt, operator_run
from apps.llm_gateway import gateway
from apps.memory import context as memory_context
from apps.personas.models import Persona
from common import enums as E


class Command(BaseCommand):
    help = "Persona pravi bogatiji artefakt (battlecard/outreach/plan-naloga/objava)."

    def add_arguments(self, p):
        p.add_argument("--persona", default="P-00001")
        p.add_argument("--vrsta", required=True,
                       help=f"Jedna od: {', '.join(zadaci.ZADACI)}.")
        p.add_argument("--ulaz", required=True,
                       help="Konkretan unos: konkurent, prospekt, nalog ili tema.")
        p.add_argument("--actor", default="user:slobodan")
        p.add_argument("--pun-kontekst", action="store_true")

    def handle(self, *args, **o):
        if not o["actor"].startswith("user:"):
            raise CommandError("--actor mora da počne sa 'user:'.")
        try:
            z = zadaci.nadji(o["vrsta"])
        except KeyError as e:
            raise CommandError(str(e)) from e
        try:
            persona = Persona.objects.get(public_id=o["persona"])
        except Persona.DoesNotExist as e:
            raise CommandError(f"Nema persone: {o['persona']}") from e

        ulaz = o["ulaz"]
        upit = z.upit.format(ulaz=ulaz)
        uputstvo = z.uputstvo.format(ulaz=ulaz)
        now = timezone.now()
        with bind(actor_id=o["actor"]):
            run = operator_run(persona, now)
            pack = memory_context.build(
                persona, run, E.RetrievalProfile.CONTENT_CREATION, query=upit, now=now)
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"# {persona.public_id} ({persona.display_name}) · "
                f"{z.naziv} · ulaz: {ulaz}"))
            ids = pack.record.vestina_ids or []
            self.stdout.write(f"veština u kontekstu: {len(ids)} · upit: {upit}")
            if o["pun_kontekst"]:
                self.stdout.write(self.style.MIGRATE_HEADING("\n## Pun kontekst:"))
                self.stdout.write(pack.text)

            from apps.content.lessons import prompt_section
            from apps.personas.org import prompt_section as org_section
            rules = prompt_section(persona)
            who = org_section(persona, now=now)
            gen = gateway.generate(
                E.LLMPurpose.CONTENT_DRAFT, _system_prompt(persona),
                (f"{who}\n\n" if who else "") + f"{pack.text}\n\n"
                + (f"{rules}\n\n" if rules else "")
                + f"## zadatak\n{uputstvo}",
                persona=persona, run=run, context_pack=pack.record, now=now,
                brief={"vrsta": z.kljuc, "ulaz": ulaz,
                       "language": persona.primary_locale})

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n## Artefakt ({gen.provider}, {gen.amount_eur_cents}¢):"))
        self.stdout.write(gen.text)
        if gen.fallbacks:
            self.stdout.write(f"\n(fallback rute: {gen.fallbacks})")
