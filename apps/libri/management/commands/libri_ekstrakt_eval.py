"""Merenje LLM ekstraktora tvrdnji vs determinističke osnove (ADR-0031 opcija B).

    python manage.py libri_ekstrakt_eval [--dokument <document_id>]

LLM je POJAČAVAČ nad osnovom. Kad je spoljni model isključen (LLM_EXTERNAL_ENABLED
false ili nema rute/ključa), ekstrakt pada na osnovu, pa su brojevi JEDNAKI.
Dijagnostika pokazuje gde se gubi: `sirovo` = koliko model vrati, `uzemljeno` =
koliko prođe filter. Po delu se vidi razlog završetka (end_turn / max_tokens /
EMPTY_RESPONSE / timeout…) — tako znamo da li filter seče ili model vraća malo.
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
    d = ekstrakt.meri(blokovi)  # jedan prolaz modela
    llm = d["uzemljeno"] if (d["model_zvan"] and d["uzemljeno"] > 0) else osnova
    return {"osnova": osnova, "llm": llm, "sirovo": d["sirovo"],
            "uzemljeno": d["uzemljeno"], "model_zvan": d["model_zvan"],
            "delovi": d.get("delovi", [])}


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

    def _ispis(self, naziv: str, m: dict):
        self.stdout.write(
            f"{naziv} — osnova: {m['osnova']}, LLM: {m['llm']} "
            f"(model vratio {m['sirovo']}, prošlo uzemljenje {m['uzemljeno']})")
        for i, x in enumerate(m["delovi"]):
            self.stdout.write(
                f"    deo {i}: vratio {x['sirovo']}, uzemljeno {x['uzemljeno']}, "
                f"razlog {x['razlog']}")

    def handle(self, *args, **options):
        rez = run_eval(options["dokument"] or None)
        stanje = ("UKLJUČEN" if rez["spolja_ukljuceno"]
                  else "isključen (fallback na osnovu)")
        self.stdout.write(f"Spoljni model: {stanje}")
        self._ispis("Zlatni skup", rez["zlatni"])
        if "dokument" in rez:
            self._ispis("Dokument", rez["dokument"])
        if not rez["zlatni"]["model_zvan"]:
            self.stdout.write(
                "Napomena: model nije zvan (isključeno ili nema ključa/rute) — "
                "brojevi su jednaki osnovi.")
