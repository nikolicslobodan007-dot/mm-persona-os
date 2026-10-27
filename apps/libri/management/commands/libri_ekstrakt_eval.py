"""Merenje LLM ekstraktora tvrdnji vs determinističke osnove (ADR-0031 opcija B).

    python manage.py libri_ekstrakt_eval [--dokument <document_id>]

LLM je POJAČAVAČ nad osnovom. Kad je spoljni model isključen (LLM_EXTERNAL_ENABLED
false ili nema rute/ključa), ekstrakt pada na osnovu, pa su brojevi JEDNAKI.
Dijagnostika pokazuje gde se gubi: `sirovo` = koliko model vrati, `uzemljeno` =
koliko prođe filter uzemljenja. Ako je sirovo veliko a uzemljeno malo → filter
seče (prag/parafraza); ako je sirovo malo → model vraća malo (prompt).
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


def _mer(blokovi: list) -> dict:
    osnova = len(tvrdnje.izvuci(blokovi))
    d = ekstrakt.meri(blokovi)  # jedan poziv modela
    llm = d["uzemljeno"] if (d["model_zvan"] and d["uzemljeno"] > 0) else osnova
    return {"osnova": osnova, "llm": llm, "sirovo": d["sirovo"],
            "uzemljeno": d["uzemljeno"], "model_zvan": d["model_zvan"]}


def run_eval(document_id: str | None = None) -> dict:
    blokovi = [_stub(i, t) for i, (t, _subj) in enumerate(TVRDNJE_ZLATNE)]
    rez = {
        "spolja_ukljuceno": bool(getattr(settings, "LLM_EXTERNAL_ENABLED", False)),
        "zlatni": _mer(blokovi),
    }
    if document_id:
        from apps.libri.models import LibriDocument

        dok = LibriDocument.objects.filter(document_id=document_id).first()
        if dok is not None:
            rez["dokument"] = _mer(list(dok.blocks.all()))
    return rez


class Command(BaseCommand):
    help = "Meri LLM ekstraktor tvrdnji vs determinističku osnovu (ADR-0031 opcija B)."

    def add_arguments(self, parser):
        parser.add_argument("--dokument", default="",
                            help="document_id stvarnog dokumenta (opciono).")

    def _red(self, naziv: str, m: dict) -> str:
        return (f"{naziv} — osnova: {m['osnova']}, LLM: {m['llm']} "
                f"(model vratio {m['sirovo']}, prošlo uzemljenje {m['uzemljeno']})")

    def handle(self, *args, **options):
        rez = run_eval(options["dokument"] or None)
        stanje = ("UKLJUČEN" if rez["spolja_ukljuceno"]
                  else "isključen (fallback na osnovu)")
        self.stdout.write(f"Spoljni model: {stanje}")
        self.stdout.write(self._red("Zlatni skup", rez["zlatni"]))
        if "dokument" in rez:
            self.stdout.write(self._red("Dokument", rez["dokument"]))
        if not rez["zlatni"]["model_zvan"]:
            self.stdout.write(
                "Napomena: model nije zvan (isključeno ili nema ključa/rute) — "
                "brojevi su jednaki osnovi.")
