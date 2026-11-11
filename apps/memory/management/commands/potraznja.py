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


def _praznina(n: int, d: float | None, prag: float) -> bool:
    """Praznina = NEMA nijednog pokrića za temu: ni veštine u diviziji (n==0),
    ni semantički bliske (d >= prag, ili model offline). Dovoljno je jedno
    pokriće da tema ne bude praznina — zato `sales` sa 36 veština nije praznina
    ni kad je gola reč „Prodaja" semantički taman iznad praga."""
    pokriva_divizija = n > 0
    pokriva_semantika = d is not None and d < prag
    return not (pokriva_divizija or pokriva_semantika)


def praznine_ekipe(prag: float = 0.45, najvise: int = 20) -> list[dict]:
    """ADR-0137 — praznine znanja CELE ekipe: distinct niše svih persona, one
    bez pokrića (demand za ulov). Vraća [{slug, naziv, najbliza, u_domenu}],
    od najveće razdaljine ka manjoj. Čita, ništa ne menja. Mera je po distinct
    niši (ne po persona×niša), pa je jeftino i kad ekipa naraste."""
    from apps.personas.models import PersonaTagLink

    nise = (PersonaTagLink.objects
            .filter(tag__category="niche")
            .values_list("tag__slug", "tag__name").distinct())
    out: list[dict] = []
    for slug, naziv in nise:
        d = context.najbliza_distanca(naziv)
        n = context.broj_u_diviziji(slug)
        if _praznina(n, d, prag):
            out.append({"slug": slug, "naziv": naziv, "najbliza": d, "u_domenu": n})
    out.sort(key=lambda g: -(g["najbliza"] if g["najbliza"] is not None else 2.0))
    return out[:najvise]


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
            gap = _praznina(n, d, prag)
            oznaka = "PRAZNINA" if gap else "OK"
            blizina = "model offline" if d is None else f"najbliža {d:.3f}"
            self.stdout.write(
                f"- {naziv:<16} tež {tez:.2f} · u domenu {n:>3} · {oznaka} ({blizina})")
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
