"""Merenje izvlačenja tvrdnji na zlatnom skupu (ADR-0031 sloj 4a, Canon §21).

    python manage.py libri_tvrdnje_eval

Deterministički ekstraktor (bez LLM), pa merenje radi svuda — i u gejtu i na
produkciji. Meri preciznost (koliko izvučenih tvrdnji je tačno) i odziv (koliko
očekivanih je uhvaćeno) na `golden.TVRDNJE_ZLATNE`. Ovo je donja granica pre nego
što LLM uđe kao zamenljiv sloj kroz isti `tvrdnje.izvuci`.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.core.management.base import BaseCommand

from apps.libri import tvrdnje
from apps.libri.golden import TVRDNJE_ZLATNE


def _stub(i: int, text: str):
    return SimpleNamespace(
        block_type="paragraph", text=text, block_id=f"blk_{i:06d}", source_page=1,
    )


def run_eval() -> dict:
    izvuceno = 0
    tacno = 0
    ocekivano = sum(1 for _, subj in TVRDNJE_ZLATNE if subj)
    uhvaceno = 0
    lazno = []
    promaseno = []
    for i, (text, subj) in enumerate(TVRDNJE_ZLATNE):
        kandidati = tvrdnje.izvuci([_stub(i, text)])
        subjekti = [k["subject"] for k in kandidati]
        izvuceno += len(kandidati)
        if subj:
            if subj in subjekti:
                uhvaceno += 1
            else:
                promaseno.append((text, subj))
        tacno += sum(1 for s in subjekti if s == subj)
        if not subj and kandidati:
            lazno.append((text, subjekti))
    return {
        "preciznost": (tacno / izvuceno) if izvuceno else 1.0,
        "odziv": (uhvaceno / ocekivano) if ocekivano else 1.0,
        "izvuceno": izvuceno, "tacno": tacno, "ocekivano": ocekivano,
        "lazno": lazno, "promaseno": promaseno,
    }


class Command(BaseCommand):
    help = "Izmeri preciznost/odziv izvlačenja tvrdnji na zlatnom skupu."

    def handle(self, *args, **opts):
        r = run_eval()
        self.stdout.write(
            f"tvrdnje (osnova) · preciznost {r['preciznost']:.2f} · "
            f"odziv {r['odziv']:.2f} · izvučeno {r['izvuceno']} "
            f"(tačno {r['tacno']}) · očekivano {r['ocekivano']}")
        for text, subjekti in r["lazno"]:
            self.stdout.write(f"  lažno: {text!r} → {subjekti}")
        for text, subj in r["promaseno"]:
            self.stdout.write(f"  promašeno: {text!r} → očekivano {subj!r}")
