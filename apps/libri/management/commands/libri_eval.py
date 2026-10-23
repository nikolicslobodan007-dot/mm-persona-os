"""Merenje semantičke pretrage Libri blokova na zlatnom skupu (ADR-0031 sloj 3).

    python manage.py libri_eval
    python manage.py libri_eval --k 5

Canon §21, isti obrazac kao `memory_eval` / `vestina_eval`: napravi privremeni
dokument sa zlatnim blokovima, embeduje ih, postavi pitanja i meri koliko je
puta tačan blok u prvih k (hit@k), prosečan recipročan rang (MRR) i vreme po
upitu (p95). Sve se poništava na kraju (rollback). Pravi semantički model se
poziva samo gde je dostupan (produkcija); u gejt-slici model nije prisutan.
"""

from __future__ import annotations

import time
from statistics import mean

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.context import bind
from apps.libri import golden, vektori
from apps.libri.models import Block, LibriDocument


def run_eval(k: int = 5) -> dict | None:
    """Vrati metrike, ili None ako semantički model nije dostupan (offline)."""
    with bind(actor_id="service:libri-eval"), transaction.atomic():
        dok = LibriDocument.objects.create(
            document_id="doc_eval_sloj3", version_id="v1",
            title="Eval sloj 3", language="sr-Latn", script="latin",
            pages=1, schema_version="lkp-0.1", ingested_at=timezone.now(),
        )
        blokovi = Block.objects.bulk_create([
            Block(document=dok, block_id=bid, block_type="paragraph", text=tekst,
                  language="sr-Latn", order=i + 1, extraction_confidence=0.9)
            for i, (bid, tekst) in enumerate(golden.BLOKOVI)
        ])
        upis = vektori.embeduj(blokovi)
        if upis["upisano"] == 0:
            transaction.set_rollback(True)
            return None
        ranks, times, misses = [], [], []
        for q, expected in golden.PITANJA:
            t0 = time.perf_counter()
            got = vektori.pretrazi(q, top_k=20, min_confidence=0.6)
            times.append((time.perf_counter() - t0) * 1000)
            ids = [b.block_id for b, _ in (got or [])]
            rank = ids.index(expected) + 1 if expected in ids else None
            ranks.append(rank)
            if rank is None or rank > k:
                misses.append((q, expected, ids[:k]))
        transaction.set_rollback(True)
    return {
        "hit_at_k": sum(1 for r in ranks if r and r <= k) / len(ranks),
        "mrr": mean(1 / r if r else 0 for r in ranks),
        "p95_ms": sorted(times)[int(0.95 * (len(times) - 1))],
        "misses": misses,
        "k": k,
    }


class Command(BaseCommand):
    help = "Izmeri hit@k i MRR semantičke pretrage Libri blokova na zlatnom skupu."

    def add_arguments(self, parser):
        parser.add_argument("--k", type=int, default=5)

    def handle(self, *args, k, **opts):
        from apps.memory.embeddings import vestina_model_key

        r = run_eval(k)
        if r is None:
            self.stdout.write(self.style.WARNING(
                "Semantički model nije dostupan (offline) — merenje nije izvršeno."))
            return
        self.stdout.write(
            f"model {vestina_model_key()} · hit@{k} {r['hit_at_k']:.2f} · "
            f"MRR {r['mrr']:.2f} · p95 {r['p95_ms']:.0f} ms · "
            f"{len(golden.PITANJA)} pitanja")
        for q, expected, got in r["misses"]:
            self.stdout.write(f"  promašaj: {q!r} → očekivano {expected}, dobijeno {got}")
