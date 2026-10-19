"""Merenje rangiranja veština na zlatnom skupu. ADR-0120; Canon §21.

    python manage.py vestina_eval
    python manage.py vestina_eval --k 10

Pušta srpske upite iz `golden_vestine.PAROVI` kroz PRAVO rangiranje koje
paket koristi (`context._rangiraj_vestine`) i meri gde završi tačna veština:
  - puni@4   — koliko tačnih uđe U CELINI, sa koracima (ADR-0112, VESTINE_PUNIH);
  - top@k    — koliko ih je u prvih k (podrazumevano 10);
  - MRR      — prosečan recipročan rang;
  - p95 ms   — vreme po upitu.

Meri nad onim što je STVARNO uvezeno u bazu — ne pravi privremeni korpus —
jer broj mora da odgovara ponašanju u pogonu (Canon §21, ADR-0033). Na vrhu
prijavi da li je išao semantički put (model dostupan) ili leksički fallback
(ADR-0009), jer bez toga bi nizak skor mogao da se pročita kao loš model, a
zapravo znači da vektori nisu tu.

Isti alat ostaje stalna mera, kao `memory_eval`: posle svake promene modela
ili korpusa, broj pokazuje da li je nameštanje pomoglo ili odmoglo.
"""

from __future__ import annotations

import time
from statistics import mean

from django.core.management.base import BaseCommand

from apps.memory import context, embeddings
from apps.memory.golden_vestine import PAROVI


def run_eval(k: int = 10) -> dict:
    ranks: list[int | None] = []
    times: list[float] = []
    misses: list[tuple[str, str, list[str]]] = []
    for upit, tacno in PAROVI:
        t0 = time.perf_counter()
        poredak = context._rangiraj_vestine(None, upit, "")
        times.append((time.perf_counter() - t0) * 1000)
        subjekti = [f.subject for f in poredak]
        rang = subjekti.index(tacno) + 1 if tacno in subjekti else None
        ranks.append(rang)
        if rang is None or rang > context.VESTINE_PUNIH:
            misses.append((upit, tacno, subjekti[: context.VESTINE_PUNIH]))
    n = len(ranks)
    return {
        "puni_at_4": sum(1 for r in ranks if r and r <= context.VESTINE_PUNIH) / n,
        "top_at_k": sum(1 for r in ranks if r and r <= k) / n,
        "mrr": mean(1 / r if r else 0 for r in ranks),
        "p95_ms": sorted(times)[int(0.95 * (n - 1))],
        "misses": misses,
        "k": k,
        "n": n,
    }


class Command(BaseCommand):
    help = "Izmeri puni@4, top@k i MRR rangiranja veština na zlatnom skupu (ADR-0120)."

    def add_arguments(self, parser):
        parser.add_argument("--k", type=int, default=10)

    def handle(self, *args, k, **opts):
        try:
            embeddings.embed_vestina("provera dostupnosti modela")
            put = f"semantički ({embeddings.vestina_model_key()})"
        except Exception:  # noqa: BLE001 — merenje radi i bez modela
            put = "LEKSIČKI fallback (model nedostupan — vektori nisu tu)"

        r = run_eval(k)
        self.stdout.write(
            f"put {put} · puni@{context.VESTINE_PUNIH} {r['puni_at_4']:.2f} · "
            f"top@{k} {r['top_at_k']:.2f} · MRR {r['mrr']:.3f} · "
            f"p95 {r['p95_ms']:.0f} ms · {r['n']} upita")
        for upit, tacno, vrh in r["misses"]:
            self.stdout.write(f"  promašaj: {upit!r} → očekivano {tacno}, vrh {vrh}")
