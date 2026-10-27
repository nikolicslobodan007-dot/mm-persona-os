"""Merenje LLM ekstraktora tvrdnji vs determinističke osnove (ADR-0031 opcija B).

    python manage.py libri_ekstrakt_eval [--dokument <document_id>]

LLM je POJAČAVAČ nad osnovom. Kad je spoljni model isključen (LLM_EXTERNAL_ENABLED
false ili nema rute), ekstrakt pada na osnovu, pa su brojevi JEDNAKI — merenje
pravog modela dolazi kad se izabere provajder (`data_training_allowed`). Ovde se
vidi koliko LLM dodaje nad osnovom: na zlatnom skupu i na stvarnom dokumentu.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.libri import ekstrakt, tvrdnje
from apps.libri.golden import TVRDNJE_ZLATNE


def _stub(i: int, text: str):
    return SimpleNamespace(block_type="paragraph", text=text,
                           block_id=f"blk_{i:06d}", source_page=1)


def run_eval(document_id: str | None = None) -> dict:
    blokovi = [_stub(i, t) for i, (t, _subj) in enumerate(TVRDNJE_ZLATNE)]
    rez = {
        "spolja_ukljuceno": bool(getattr(settings, "LLM_EXTERNAL_ENABLED", False)),
        "zlatni": {"osnova": len(tvrdnje.izvuci(blokovi)),
                   "llm": len(ekstrakt.izvuci(blokovi))},
    }
    if document_id:
        from apps.libri.models import LibriDocument

        dok = LibriDocument.objects.filter(document_id=document_id).first()
        if dok is not None:
            bl = list(dok.blocks.all())
            rez["dokument"] = {"osnova": len(tvrdnje.izvuci(bl)),
                               "llm": len(ekstrakt.izvuci(bl))}
    return rez


class Command(BaseCommand):
    help = "Meri LLM ekstraktor tvrdnji vs determinističku osnovu (ADR-0031 opcija B)."

    def add_arguments(self, parser):
        parser.add_argument("--dokument", default="",
                            help="document_id stvarnog dokumenta (opciono).")

    def handle(self, *args, **options):
        rez = run_eval(options["dokument"] or None)
        stanje = ("UKLJUČEN" if rez["spolja_ukljuceno"]
                  else "isključen (fallback na osnovu)")
        self.stdout.write(f"Spoljni model: {stanje}")
        z = rez["zlatni"]
        self.stdout.write(f"Zlatni skup — osnova: {z['osnova']}, LLM: {z['llm']}")
        if "dokument" in rez:
            d = rez["dokument"]
            self.stdout.write(f"Dokument — osnova: {d['osnova']}, LLM: {d['llm']}")
        if not rez["spolja_ukljuceno"]:
            self.stdout.write(
                "Napomena: spoljni model isključen — brojevi su jednaki. Merenje "
                "pravog modela dolazi kad se izabere provajder (data_training_allowed).")
