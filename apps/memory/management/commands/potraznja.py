"""manage.py potraznja — demand-driven ulov (ADR-0131, stavka 1).

Meri PRAZNINU u znanju persone po njenim nišama: za svaku nišu nađe semantičku
razdaljinu najbliže SLOBODNA veštine; gde je predaleko (iznad praga) — to je
tema za ulov, pa ispiše spreman `signali --teme` upit. Isti most niša↔divizija
koji rangira veštine ovde meri i prazninu.

Samo ČITA: bez upisa, bez ulova, bez spoljašnje akcije. Uvoz sakupljenog i dalje
traži čoveka (`--actor user:`, ADR-0074).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.memory import context
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Izmeri prazninu u znanju persone po nišama; predloži teme za ulov."

    def add_arguments(self, p):
        p.add_argument("--persona", default="P-00001")
        p.add_argument("--prag", type=float, default=0.45,
                       help="Kosinusna razdaljina iznad koje je tema PRAZNINA.")
        p.add_argument("--teme", default="",
                       help="Dodatne teme van niša, zarezom (npr. 'video,rag').")

    def handle(self, *args, **o):
        try:
            persona = Persona.objects.get(public_id=o["persona"])
        except Persona.DoesNotExist as e:
            raise CommandError(f"Nema persone: {o['persona']}") from e

        prag = o["prag"]
        niche = [(link.tag.slug, link.tag.name, float(link.weight))
                 for link in persona.tag_links.filter(
                     tag__category="niche").select_related("tag")]
        rucne = [(t.strip(), t.strip(), 1.0)
                 for t in o["teme"].split(",") if t.strip()]
        teme = niche + rucne
        if not teme:
            self.stdout.write("Persona nema niša ni zadatih tema — ništa za meriti.")
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# Potražnja znanja · {persona.public_id} "
            f"({persona.display_name}) · prag={prag}"))

        praznine: list[str] = []
        for slug, naziv, tez in sorted(teme, key=lambda x: -x[2]):
            d = context.najbliza_distanca(naziv)
            n = context.broj_u_diviziji(slug)
            if d is None:
                gap = n == 0
                status = "? model offline" + ("" if n else " · nema veštine u diviziji")
            else:
                gap = d >= prag
                status = f"{'PRAZNINA' if gap else 'OK'} (najbliža {d:.3f})"
            self.stdout.write(f"- {naziv:<16} tež {tez:.2f} · u domenu {n:>3} · {status}")
            if gap:
                praznine.append(slug)

        if praznine:
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n## Predlog ulova (čovek pokreće, ADR-0074):"))
            for slug in praznine:
                self.stdout.write(f'  python manage.py signali --teme "{slug}"')
        else:
            self.stdout.write(self.style.SUCCESS(
                "\nNema praznina iznad praga — baza pokriva niše persone."))
