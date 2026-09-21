"""Merenje retrieval-a na zlatnom skupu. Canon §21, Memory v0.1 §20.

    python manage.py memory_eval
    python manage.py memory_eval --model local-hash-v1 --k 5

Pravi privremenu personu, upiše 24 memorije, postavi 12 pitanja i meri
koliko puta je tačna memorija u prvih k (hit@k), prosečan recipročan rang
(MRR) i vreme po upitu. Sve se poništava na kraju.
"""

from __future__ import annotations

import time
from statistics import mean

from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings

from api.context import bind
from apps.memory import golden, retrieval
from apps.memory.writer import MemoryInput, write
from apps.personas.models import Persona
from common import enums as E


def run_eval(k: int = 5) -> dict:
    with bind(actor_id="service:memory-eval"), transaction.atomic():
        p = Persona.objects.create(
            public_id="P-99990", slug="memory-eval", display_name="Eval (AI)",
            persona_type=E.PersonaType.SIMULATION_ONLY, status=E.PersonaStatus.DRAFT,
            runtime_environment=E.RuntimeEnvironment.SIMULATION, trust_level=E.TrustLevel.L0,
            disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE, disclosure_required=True,
            primary_locale="sr-Latn-RS", timezone="Europe/Belgrade",
        )
        ids: dict[str, str] = {}
        for key, mtype, title, content, tags in golden.MEMORIES:
            res = write(p, MemoryInput(
                memory_type=mtype, title=title, content=content, tags=list(tags),
                source_kind=E.SourceKind.SYSTEM_OBSERVATION, provenance=E.Provenance.OBSERVED,
                salience=0.6, source_event_id=f"golden:{key}"))
            ids[str(res.memory.id)] = key
        ranks, times, misses = [], [], []
        for q, expected in golden.QUERIES:
            t0 = time.perf_counter()
            got = [ids[str(s.memory.id)] for s in retrieval.retrieve(
                p, q, E.RetrievalProfile.RESEARCH, top_k=20)]
            times.append((time.perf_counter() - t0) * 1000)
            rank = got.index(expected) + 1 if expected in got else None
            ranks.append(rank)
            if rank is None or rank > k:
                misses.append((q, expected, got[:k]))
        transaction.set_rollback(True)
    return {
        "hit_at_k": sum(1 for r in ranks if r and r <= k) / len(ranks),
        "mrr": mean(1 / r if r else 0 for r in ranks),
        "p95_ms": sorted(times)[int(0.95 * (len(times) - 1))],
        "misses": misses,
        "k": k,
    }


class Command(BaseCommand):
    help = "Izmeri hit@k i MRR trenutnog embedding modela na zlatnom skupu."

    def add_arguments(self, parser):
        parser.add_argument("--model", default=None)
        parser.add_argument("--k", type=int, default=5)

    def handle(self, *args, model, k, **opts):
        ctx = override_settings(EMBEDDING_MODEL=model) if model else None
        if ctx:
            ctx.enable()
        try:
            from apps.memory.embeddings import model_key

            r = run_eval(k)
            self.stdout.write(
                f"model {model_key()} · hit@{k} {r['hit_at_k']:.2f} · MRR {r['mrr']:.2f} "
                f"· p95 {r['p95_ms']:.0f} ms · {len(golden.QUERIES)} pitanja")
            for q, expected, got in r["misses"]:
                self.stdout.write(f"  promašaj: {q!r} → očekivano {expected}, dobijeno {got}")
        finally:
            if ctx:
                ctx.disable()
