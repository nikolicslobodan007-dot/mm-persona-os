"""Merenje LLM analize dosija — hipoteze/pitanja (ADR-0031 sloj 4c, §9/§10).

    python manage.py libri_analiza_eval --dokument <document_id>

§9/§10 su INFERRED (sinteza nad činjenicama), pa NEMA zlatnog skupa kao kod
tvrdnji/entiteta — meri se samo koliko stavki prođe brane (oslonac na bar jedan
postojeći block_id). Kad je spoljni model isključen ili nema nijedne tvrdnje,
model se ne zove (model_zvan=False) i sekcije 9/10 ostaju prazne.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.libri import analiza, dosije


def meri_dokument(document_id: str) -> dict | None:
    """Merenje LLM analize na stvarnom dokumentu; None ako dokument ne postoji."""
    from apps.libri.models import LibriDocument

    dok = LibriDocument.objects.filter(document_id=document_id).first()
    if dok is None:
        return None
    prikup = dosije._prikupi(dok)
    return analiza.meri(prikup, prikup["blok_idovi"])


class Command(BaseCommand):
    help = "Meri LLM analizu dosija (hipoteze/pitanja) na stvarnom dokumentu."

    def add_arguments(self, parser):
        parser.add_argument("--dokument", default="",
                            help="document_id stvarnog dokumenta (obavezno).")

    def handle(self, *args, **options):
        doc_id = options["dokument"] or ""
        if not doc_id:
            self.stdout.write("Zadaj --dokument <document_id>.")
            return
        stanje = ("UKLJUČEN" if getattr(settings, "LLM_EXTERNAL_ENABLED", False)
                  else "isključen (fallback na prazno)")
        self.stdout.write(f"Spoljni model: {stanje}")
        m = meri_dokument(doc_id)
        if m is None:
            self.stdout.write(f"Dokument ne postoji: {doc_id}.")
            return
        self.stdout.write(
            f"Dokument {doc_id} — hipoteze: {m['hipoteze']}, pitanja: {m['pitanja']} "
            f"(model_zvan={m['model_zvan']}, razlog {m['razlog']})")
        if not m["model_zvan"]:
            self.stdout.write(
                "Napomena: model nije zvan (isključeno, bez rute, ili nema tvrdnji) — "
                "sekcije 9/10 ostaju prazne.")
