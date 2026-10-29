"""Merenje izvlačenja entiteta i odnosa na zlatnom skupu (ADR-0031 sloj 4b).

    python manage.py libri_entiteti_eval [--dokument <document_id>]

Deterministički ekstraktor (bez LLM), pa merenje radi svuda — i u gejtu i na
produkciji. Meri preciznost (koliko izvučenih je tačno) i odziv (koliko očekivanih
je uhvaćeno), zasebno za entitete i za odnose, na `golden.GRAF_ZLATNI`. Ovo je
donja granica pre nego što LLM uđe kao zamenljiv sloj kroz isti `entiteti.izvuci_*`.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.libri import ekstrakt_entiteti, entiteti
from apps.libri.golden import GRAF_ZLATNI


def _stub(i: int, text: str):
    return SimpleNamespace(
        block_type="paragraph", text=text, block_id=f"blk_{i:06d}", source_page=1,
    )


def _pr(tp: int, fp: int, fn: int) -> tuple[float, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r


def run_eval() -> dict:
    e_tp = e_fp = e_fn = o_tp = o_fp = o_fn = 0
    lazno: list = []
    promaseno: list = []
    for i, (text, oe, oo) in enumerate(GRAF_ZLATNI):
        blok = _stub(i, text)
        ent = entiteti.izvuci_entitete([blok])
        odn = entiteti.izvuci_odnose([blok], ent)
        got_e = {(x["name"], x["kind"]) for x in ent}
        got_o = {(x["subject"], x["relation_type"], x["object"]) for x in odn}
        want_e, want_o = set(oe), set(oo)
        e_tp += len(got_e & want_e)
        e_fp += len(got_e - want_e)
        e_fn += len(want_e - got_e)
        o_tp += len(got_o & want_o)
        o_fp += len(got_o - want_o)
        o_fn += len(want_o - got_o)
        lazno += [("ent", text, x) for x in got_e - want_e]
        lazno += [("odn", text, x) for x in got_o - want_o]
        promaseno += [("ent", text, x) for x in want_e - got_e]
        promaseno += [("odn", text, x) for x in want_o - got_o]
    pe, re_ = _pr(e_tp, e_fp, e_fn)
    po, ro = _pr(o_tp, o_fp, o_fn)
    return {
        "preciznost_entiteti": pe, "odziv_entiteti": re_,
        "preciznost_odnosa": po, "odziv_odnosa": ro,
        "entiteti": {"tp": e_tp, "fp": e_fp, "fn": e_fn},
        "odnosi": {"tp": o_tp, "fp": o_fp, "fn": o_fn},
        "lazno": lazno, "promaseno": promaseno,
    }


def meri_dokument(document_id: str) -> dict | None:
    """LLM pojačavač vs deterministička osnova na STVARNOM dokumentu.

    Golden (`run_eval`) meri kvalitet osnove; ovo meri koliko LLM dodaje nad
    pravim tekstom. Kad je spoljni model isključen, `ekstrakt_entiteti.meri`
    ne zove model, pa su LLM brojevi 0 i vredi osnova (fallback ugovor).
    """
    from apps.libri.models import LibriDocument

    dok = LibriDocument.objects.filter(document_id=document_id).first()
    if dok is None:
        return None
    blokovi = list(dok.blocks.all())
    osnova_e = entiteti.izvuci_entitete(blokovi)
    osnova_o = entiteti.izvuci_odnose(blokovi, osnova_e)
    d = ekstrakt_entiteti.meri(blokovi)
    return {
        "osnova_entiteti": len(osnova_e), "osnova_odnosi": len(osnova_o),
        "model_zvan": d["model_zvan"],
        "entiteti_sirovo": d["entiteti_sirovo"], "entiteti_uzemljeno": d["entiteti_uzemljeno"],
        "odnosi_sirovo": d["odnosi_sirovo"], "odnosi_uzemljeno": d["odnosi_uzemljeno"],
        "delovi": d.get("delovi", []),
    }


class Command(BaseCommand):
    help = "Izmeri preciznost/odziv izvlačenja entiteta i odnosa na zlatnom skupu."

    def add_arguments(self, parser):
        parser.add_argument("--dokument", default="",
                            help="document_id — LLM pojačavač vs osnova (opciono).")

    def handle(self, *args, **options):
        r = run_eval()
        self.stdout.write(
            f"entiteti (osnova) · preciznost {r['preciznost_entiteti']:.2f} · "
            f"odziv {r['odziv_entiteti']:.2f} · {r['entiteti']}")
        self.stdout.write(
            f"odnosi (osnova) · preciznost {r['preciznost_odnosa']:.2f} · "
            f"odziv {r['odziv_odnosa']:.2f} · {r['odnosi']}")
        for vrsta, text, x in r["lazno"]:
            self.stdout.write(f"  lažno-{vrsta}: {x!r} ← {text!r}")
        for vrsta, text, x in r["promaseno"]:
            self.stdout.write(f"  promašeno-{vrsta}: {x!r} ← {text!r}")

        doc_id = options.get("dokument") or ""
        if not doc_id:
            return
        stanje = ("UKLJUČEN" if getattr(settings, "LLM_EXTERNAL_ENABLED", False)
                  else "isključen (fallback na osnovu)")
        self.stdout.write(f"Spoljni model: {stanje}")
        m = meri_dokument(doc_id)
        if m is None:
            self.stdout.write(f"Dokument ne postoji: {doc_id}.")
            return
        self.stdout.write(
            f"Dokument {doc_id} — entiteti osnova: {m['osnova_entiteti']}, "
            f"LLM uzemljeno: {m['entiteti_uzemljeno']} (model vratio {m['entiteti_sirovo']})")
        self.stdout.write(
            f"Dokument {doc_id} — odnosi osnova: {m['osnova_odnosi']}, "
            f"LLM uzemljeno: {m['odnosi_uzemljeno']} (model vratio {m['odnosi_sirovo']})")
        for i, x in enumerate(m["delovi"]):
            self.stdout.write(
                f"    deo {i}: entiteti {x['entiteti_uzemljeno']}/{x['entiteti_sirovo']}, "
                f"odnosi {x['odnosi_uzemljeno']}/{x['odnosi_sirovo']}, razlog {x['razlog']}")
        if not m["model_zvan"]:
            self.stdout.write(
                "Napomena: model nije zvan (isključeno ili nema ključa/rute) — "
                "vredi osnova.")
