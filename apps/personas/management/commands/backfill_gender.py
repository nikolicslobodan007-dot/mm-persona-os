"""Popuni VisualProfile.gender iz PersonaDossier.appearance_prompt (ADR-0129).

Dosije se NE menja i NE izlaže; samo se iz njegovog teksta izvede strukturan rod.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.personas.models import PersonaDossier
from apps.visuals.models import VisualProfile
from common import enums as E

_FEMALE = ("žena", "zena", "devojka", "ženska", "zenska")
_MALE = ("muškarac", "muskarac", "mladić", "mladic", "muško", "musko")


def gender_from_text(text: str) -> str:
    t = (text or "").lstrip().lower()
    if t.startswith(_FEMALE):
        return E.Gender.FEMALE.value
    if t.startswith(_MALE):
        return E.Gender.MALE.value
    return E.Gender.UNSPECIFIED.value


class Command(BaseCommand):
    help = "Popuni VisualProfile.gender iz PersonaDossier.appearance_prompt (ADR-0129)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--force", action="store_true", help="Prepiši i već postavljene vrednosti."
        )

    def handle(self, *args, **opts):
        dossiers = {
            d.persona_id: d.appearance_prompt for d in PersonaDossier.objects.all()
        }
        updated = 0
        counts = {"FEMALE": 0, "MALE": 0, "UNSPECIFIED": 0}
        for vp in VisualProfile.objects.all().iterator():
            already = vp.gender and vp.gender != E.Gender.UNSPECIFIED.value
            if already and not opts["force"]:
                continue
            g = gender_from_text(dossiers.get(vp.persona_id, ""))
            counts[g] += 1
            if vp.gender != g:
                if not opts["dry_run"]:
                    vp.gender = g
                    vp.save(update_fields=["gender"])
                updated += 1
        suffix = " (dry-run)" if opts["dry_run"] else ""
        self.stdout.write(f"gender backfill{suffix}: izmenjeno {updated}; raspodela {counts}")
