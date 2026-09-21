"""Hibridni retrieval. Canon §10.2; Memory v0.1 §6.1, §7.

    scored = retrieve(persona, "šta znam o logistici?", RetrievalProfile.RESEARCH)

Kandidati dolaze iz tri izvora i spajaju se (§7):
  1. vektorska sličnost (pgvector, kosinus) — top 60,
  2. skorašnje i najvažnije memorije — top 30,
  3. ako za trenutni model nema vektora — poslednjih 500, bez vektora.
Treći put je fallback iz §6: pad embedding servisa ne sme da ugasi pamćenje.

Konačni rang je formula R iz Canon §10.2, a svaka vraćena memorija nosi
razlaganje skora („zašto je ovo izabrano", §16.1). Retriever ne menja
memoriju (§18.1); broj prisećanja upisuje Context Builder.

Signal `relationship` je u F4 uvek 0: nema Social Graph-a (ADR-0006).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Max, Q
from django.utils import timezone
from pgvector.django import CosineDistance

from apps.memory import embeddings
from apps.memory.models import MemoryContradiction, MemoryEmbedding, MemoryItem
from common import enums as E

#: Canon §10.2 — težine formule R.
WEIGHTS = {
    "semantic": 0.30, "task_relevance": 0.18, "recency": 0.14, "salience": 0.12,
    "confidence": 0.10, "relationship": 0.08, "source_quality": 0.05, "novelty": 0.03,
}
OPEN_CONTRADICTION_PENALTY = 0.15
RECENCY_DAYS = 14.0
VECTOR_CANDIDATES = 60
RECENT_CANDIDATES = 30
FALLBACK_CANDIDATES = 500
RETRIEVABLE = (E.MemoryStatus.ACTIVE.value, E.MemoryStatus.PINNED.value)


@dataclass
class Scored:
    memory: MemoryItem
    score: float
    breakdown: dict[str, float]
    contested: bool = False


def _stems(text: str) -> set[str]:
    return {w[:5] for w in embeddings.normalize(text).split() if len(w) >= 3}


def effective_salience(m: MemoryItem, now: datetime) -> float:
    """Canon §10.2 — base · exp(−λ_type · age_days). PINNED ne bledi."""
    base = float(m.salience)
    if m.status == E.MemoryStatus.PINNED.value:
        return base
    age = max(0.0, (now - (m.event_time or m.created_at)).total_seconds() / 86400)
    return base * math.exp(-E.MEMORY_LAMBDA[E.MemoryType(m.memory_type)] * age)


def _base_qs(persona, now, memory_types, purpose):
    qs = MemoryItem.objects.filter(persona=persona, status__in=RETRIEVABLE).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    if memory_types:
        qs = qs.filter(memory_type__in=[t.value for t in memory_types])
    if purpose not in E.SENSITIVE_ALLOWED_PURPOSES:
        qs = qs.filter(sensitivity__lt=E.SENSITIVE_FROM)
    return qs


def retrieve(persona, query: str, profile: E.RetrievalProfile, *, now: datetime | None = None,
             top_k: int | None = None, memory_types: list[E.MemoryType] | None = None,
             purpose: E.LLMPurpose | None = None) -> list[Scored]:
    now = now or timezone.now()
    purpose = purpose or E.PROFILE_PURPOSE[profile]
    top_k = top_k or E.PROFILE_TOP_K[profile]
    qs = _base_qs(persona, now, memory_types, purpose)
    key = embeddings.model_key()
    qv = embeddings.embed(query) if query.strip() else None

    semantic: dict[str, float] = {}
    if qv is not None:
        rows = (MemoryEmbedding.objects.filter(memory__in=qs, model_key=key)
                .annotate(dist=CosineDistance("embedding", qv))
                .order_by("dist").values_list("memory_id", "dist")[:VECTOR_CANDIDATES])
        semantic = {str(mid): max(0.0, 1.0 - float(dist)) for mid, dist in rows}

    def top(order: str, n: int) -> set[str]:
        return {str(i) for i in qs.order_by(order).values_list("id", flat=True)[:n]}

    ids = set(semantic) | top("-event_time", RECENT_CANDIDATES)
    ids |= top("-salience", RECENT_CANDIDATES)
    if not semantic:
        ids |= top("-event_time", FALLBACK_CANDIDATES)

    items = list(qs.filter(id__in=ids).annotate(source_quality=Max("sources__confidence")))
    contested = set()
    for left, right in MemoryContradiction.objects.filter(
            persona=persona, status="OPEN").values_list("left_id", "right_id"):
        contested |= {str(left), str(right)}

    q_stems = _stems(query)
    out: list[Scored] = []
    for m in items:
        mid = str(m.id)
        m_stems = _stems(f"{m.title} {m.content} {' '.join(m.tags or [])}")
        age_days = max(0.0, (now - (m.event_time or m.created_at)).total_seconds() / 86400)
        b = {
            "semantic": round(semantic.get(mid, 0.0), 4),
            "task_relevance": round(len(q_stems & m_stems) / len(q_stems), 4) if q_stems else 0.0,
            "recency": round(math.exp(-age_days / RECENCY_DAYS), 4),
            "salience": round(effective_salience(m, now), 4),
            "confidence": float(m.confidence),
            "relationship": 0.0,
            "source_quality": float(m.source_quality or m.confidence),
            "novelty": float(m.novelty),
        }
        penalty = OPEN_CONTRADICTION_PENALTY if mid in contested else 0.0
        score = sum(WEIGHTS[k] * v for k, v in b.items()) - penalty
        b["penalty"] = penalty
        out.append(Scored(m, round(score, 4), b, contested=mid in contested))
    out.sort(key=lambda s: (-s.score, str(s.memory.id)))
    return out[:top_k]
