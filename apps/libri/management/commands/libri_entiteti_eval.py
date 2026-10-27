"""Merenje izvlačenja entiteta i odnosa na zlatnom skupu (ADR-0031 sloj 4b).

    python manage.py libri_entiteti_eval

Deterministički ekstraktor (bez LLM), pa merenje radi svuda — i u gejtu i na
produkciji. Meri preciznost (koliko izvučenih je tačno) i odziv (koliko očekivanih
je uhvaćeno), zasebno za entitete i za odnose, na `golden.GRAF_ZLATNI`. Ovo je
donja granica pre nego što LLM uđe kao zamenljiv sloj kroz isti `entiteti.izvuci_*`.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.core.management.base import BaseCommand

from apps.libri import entiteti
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


class Command(BaseCommand):
    help = "Izmeri preciznost/odziv izvlačenja entiteta i odnosa na zlatnom skupu."

    def handle(self, *args, **opts):
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
