"""Merenje semantičke pretrage pravila na zlatnom skupu. ADR-0120; Canon §21.

    python manage.py pravila_eval
    python manage.py pravila_eval --k 10

Pušta srpske upite iz `golden_pravila.PAROVI` kroz PRAVO rangiranje koje
pretraga koristi (`recnik._rangiraj_pravila`) i meri gde završi prva
prihvatljiva tačka odeljka:
  - top@1    — koliko puta je prva prihvatljiva tačka baš na vrhu;
  - top@k    — koliko ih je u prvih k (podrazumevano 10);
  - MRR      — prosečan recipročan rang;
  - p95 ms   — vreme po upitu.

Meri nad onim što je STVARNO uvezeno u bazu — ne pravi privremeni korpus — jer
broj mora da odgovara ponašanju u pogonu (Canon §21, ADR-0033). Na vrhu
prijavi da li je išao semantički put (model dostupan) ili leksički fallback
(ADR-0009): bez toga bi nizak skor mogao da se pročita kao loš model, a
zapravo znači da vektori nisu tu.

Isti alat ostaje stalna mera: posle svake promene modela ili oblika teksta,
broj pokazuje da li je nameštanje pomoglo ili odmoglo.
"""

from __future__ import annotations

import time
from statistics import mean

from django.core.management.base import BaseCommand

from apps.content import recnik
from apps.content.golden_pravila import PAROVI
from apps.memory import embeddings


def _rang_prve_prihvatljive(poredak: list, prihvatljive: tuple[int, ...]) -> int | None:
    doz = set(prihvatljive)
    for i, f in enumerate(poredak, start=1):
        if (f.object_json or {}).get("tacka") in doz:
            return i
    return None


def run_eval(k: int = 10) -> dict:
    ranks: list[int | None] = []
    times: list[float] = []
    misses: list[tuple[str, tuple[int, ...], list]] = []
    for upit, prihvatljive in PAROVI:
        t0 = time.perf_counter()
        poredak = recnik._rangiraj_pravila(upit)
        times.append((time.perf_counter() - t0) * 1000)
        rang = _rang_prve_prihvatljive(poredak, prihvatljive)
        ranks.append(rang)
        if rang is None or rang > k:
            vrh = [(f.object_json or {}).get("tacka") for f in poredak[:5]]
            misses.append((upit, prihvatljive, vrh))
    n = len(ranks)
    return {
        "top_at_1": sum(1 for r in ranks if r == 1) / n,
        "top_at_k": sum(1 for r in ranks if r and r <= k) / n,
        "mrr": mean(1 / r if r else 0 for r in ranks),
        "p95_ms": sorted(times)[int(0.95 * (n - 1))],
        "misses": misses,
        "k": k,
        "n": n,
    }


class Command(BaseCommand):
    help = "Izmeri top@1, top@k i MRR semantičke pretrage pravila (ADR-0120)."

    def add_arguments(self, parser):
        parser.add_argument("--k", type=int, default=10)

    def handle(self, *args, k, **opts):
        if not recnik.pravila_dostupna():
            self.stdout.write(self.style.ERROR(
                "Pravila nisu uvezena — nema šta da se meri (`recnik --uvezi-pravila`)."))
            return
        try:
            embeddings.embed_semanticki("provera dostupnosti modela")
            put = f"semantički ({embeddings.vestina_model_key()})"
        except Exception:  # noqa: BLE001 — merenje radi i bez modela
            put = "LEKSIČKI fallback (model nedostupan — vektori nisu tu)"

        r = run_eval(k)
        self.stdout.write(
            f"put {put} · top@1 {r['top_at_1']:.2f} · top@{k} {r['top_at_k']:.2f} · "
            f"MRR {r['mrr']:.3f} · p95 {r['p95_ms']:.0f} ms · {r['n']} upita")
        for upit, prihvatljive, vrh in r["misses"]:
            self.stdout.write(
                f"  promašaj: {upit!r} → očekivano т.{prihvatljive[0]}–{prihvatljive[-1]}, "
                f"vrh {vrh}")
