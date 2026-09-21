"""Upis memorije. Memory v0.1 §5, §10; Canon §10.2–10.4.

    result = write(persona, MemoryInput(...))

Tok (§5): tajne se odbijaju → eligibility M → dedup po izvornom događaju
i po sadržaju → upis sa izvorom → vektor → provera tvrdnje → `memory.created`.

Šta writer NE radi (§18.1): ne zove LLM, ne izmišlja pobednika kad dokaz
nije dovoljan, ne briše ništa. Protivrečnost bez jasnog pobednika ostaje
OTVORENA i obe memorije nose oznaku u kontekstu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.memory import embeddings
from apps.memory.models import (
    MemoryContradiction,
    MemoryEmbedding,
    MemoryItem,
    MemoryLink,
    MemorySource,
)
from apps.observability import bus
from common import enums as E

#: Memory v0.1 §5.1, §15 — ovo pripada trezoru tajni, ne memoriji.
_SECRET = re.compile(
    r"(?ix)"
    r"(password|lozinka|passwd|api[_-]?key|secret|token|bearer)\s*[:=]\s*\S+"
    r"|\bsk-[a-z0-9]{16,}"
    r"|\b(?:ghp|gho|github_pat)_[a-z0-9_]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
#: Canon §10.2 — `sensitivity_penalty`. Oduzima najviše 0.30 od M.
SENSITIVITY_PENALTY_WEIGHT = 0.30
#: Nova tvrdnja pobeđuje ako joj je pouzdanost bar ovoliko blizu stare.
SUPERSEDE_TOLERANCE = 0.05
WORKING_TTL = timedelta(hours=6)
_ALLOWED_PROVENANCE: dict[E.SourceKind, frozenset[E.Provenance]] = {
    E.SourceKind.SYSTEM_OBSERVATION: frozenset({E.Provenance.OBSERVED}),
    E.SourceKind.FIRST_PARTY_USER_INPUT: frozenset({E.Provenance.USER_PROVIDED}),
    E.SourceKind.PUBLIC_WEB_SOURCE: frozenset({E.Provenance.OBSERVED}),
    E.SourceKind.LLM_INFERENCE: frozenset({E.Provenance.INFERRED, E.Provenance.GENERATED}),
    E.SourceKind.SYNTHETIC_WORLD_EVENT: frozenset({E.Provenance.OBSERVED}),
}


class MemoryRejected(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class MemoryInput:
    memory_type: E.MemoryType
    content: str
    source_kind: E.SourceKind
    provenance: E.Provenance
    title: str = ""
    salience: float = 0.5
    confidence: float | None = None
    goal_relevance: float = 0.0
    novelty: float = 0.5
    relationship_relevance: float = 0.0
    future_utility: float = 0.3
    sensitivity: float = 0.0
    tags: list[str] = field(default_factory=list)
    event_time: datetime | None = None
    source_event_id: str | None = None
    source_ref: str = ""
    run: Any = None
    assertion: tuple[str, str, Any] | None = None  # (subject, predicate, value)
    status: E.MemoryStatus = E.MemoryStatus.ACTIVE


@dataclass
class WriteResult:
    outcome: str  # created / duplicate / reinforced / rejected
    memory: MemoryItem | None
    eligibility: float
    reason: str = ""
    superseded: list[MemoryItem] = field(default_factory=list)
    contradictions: list[MemoryContradiction] = field(default_factory=list)


def eligibility(m: MemoryInput, confidence: float) -> float:
    """Canon §10.2 — M, sa kaznom za osetljivost."""
    score = (0.30 * m.salience + 0.20 * m.goal_relevance + 0.15 * m.novelty
             + 0.15 * m.relationship_relevance + 0.10 * m.future_utility
             + 0.10 * confidence - SENSITIVITY_PENALTY_WEIGHT * m.sensitivity)
    return round(max(0.0, score), 4)


def _confidence(m: MemoryInput) -> float:
    lo, hi = E.SOURCE_CONFIDENCE[m.source_kind.value]
    if m.confidence is None:
        return round((lo + hi) / 2, 3)
    return round(min(hi, max(lo, m.confidence)), 3)


def _d(x: float) -> Decimal:
    return Decimal(str(round(x, 3)))


def _emb(memory: MemoryItem, text: str) -> None:
    key = embeddings.model_key()
    h = embeddings.text_hash(text)
    existing = MemoryEmbedding.objects.filter(memory=memory, model_key=key).first()
    if existing and existing.text_hash == h:
        return
    vector = embeddings.embed(text, model=key)
    MemoryEmbedding.objects.update_or_create(
        memory=memory, model_key=key,
        defaults={"embedding": vector, "dimensions": len(vector), "text_hash": h},
    )


def embed_memory(memory: MemoryItem) -> None:
    _emb(memory, f"{memory.title}\n{memory.content}")


def write(persona, m: MemoryInput, *, now: datetime | None = None) -> WriteResult:
    now = now or timezone.now()
    text = f"{m.title}\n{m.content}"
    if _SECRET.search(text):
        raise MemoryRejected("SECRET_MATERIAL",
                             "Sadržaj liči na tajnu (lozinka, ključ, token). "
                             "Tajne idu u trezor, memorija čuva samo credential_ref.")
    if m.provenance not in _ALLOWED_PROVENANCE[m.source_kind]:
        raise MemoryRejected("PROVENANCE_MISMATCH",
                             f"Izvor {m.source_kind.value} ne može imati "
                             f"provenance {m.provenance.value} (Canon §10.4).")
    if m.memory_type == E.MemoryType.SEMANTIC and m.provenance == E.Provenance.INFERRED \
            and m.assertion and m.assertion[0] == persona.public_id:
        # Canon §10.4 — izvod nikad ne postaje biografska činjenica persone.
        raise MemoryRejected("INFERRED_BIOGRAPHY",
                             "Izvedena tvrdnja o samoj personi ne upisuje se kao činjenica.")

    conf = _confidence(m)
    score = eligibility(m, conf)
    if score < E.MEMORY_ELIGIBILITY_MIN[m.memory_type]:
        return WriteResult("rejected", None, score, "LOW_ELIGIBILITY")

    with transaction.atomic():
        if m.source_event_id:
            same = MemoryItem.objects.filter(persona=persona, memory_type=m.memory_type.value,
                                             source_event_id=m.source_event_id).first()
            if same:
                return WriteResult("duplicate", same, score, "SAME_SOURCE_EVENT")

        h = embeddings.text_hash(text)
        dup = MemoryItem.objects.filter(
            persona=persona, memory_type=m.memory_type.value, content_hash=h,
            status__in=[E.MemoryStatus.ACTIVE.value, E.MemoryStatus.PINNED.value],
        ).first()
        if dup:
            _add_source(dup, m, conf, now)
            dup.confidence = _d(min(1.0, max(float(dup.confidence), conf) + 0.02))
            dup.save(update_fields=["confidence", "updated_at"])
            return WriteResult("reinforced", dup, score, "SAME_CONTENT")

        if m.assertion:
            same_claim = _active_claims(persona, m.assertion).filter(
                assertion_value=m.assertion[2]).first()
            if same_claim:
                _add_source(same_claim, m, conf, now)
                same_claim.confidence = _d(min(1.0, max(float(same_claim.confidence), conf) + 0.02))
                same_claim.save(update_fields=["confidence", "updated_at"])
                return WriteResult("reinforced", same_claim, score, "SAME_ASSERTION")

        try:
            with transaction.atomic():
                item = MemoryItem.objects.create(
                    persona=persona, memory_type=m.memory_type.value, status=m.status.value,
                    provenance=m.provenance.value, title=m.title[:220], content=m.content,
                    salience=_d(m.salience), confidence=_d(conf),
                    goal_relevance=_d(m.goal_relevance), novelty=_d(m.novelty),
                    sensitivity=_d(m.sensitivity), event_time=m.event_time or now,
                    expires_at=(now + WORKING_TTL
                                if m.memory_type == E.MemoryType.WORKING else None),
                    source_event_id=m.source_event_id, content_hash=h,
                    tags=[t.lower() for t in m.tags],
                    assertion_subject=(m.assertion[0] if m.assertion else ""),
                    assertion_predicate=(m.assertion[1] if m.assertion else ""),
                    assertion_value=(m.assertion[2] if m.assertion else None),
                    valid_from=now if m.assertion else None,
                )
        except IntegrityError:
            same = MemoryItem.objects.get(persona=persona, memory_type=m.memory_type.value,
                                          source_event_id=m.source_event_id)
            return WriteResult("duplicate", same, score, "SAME_SOURCE_EVENT")
        _add_source(item, m, conf, now)
        _emb(item, text)
        result = WriteResult("created", item, score)
        if m.assertion:
            _resolve(persona, item, m, now, result)
        bus.emit("memory.created",
                 {"memory_id": str(item.id), "memory_type": item.memory_type,
                  "salience": float(item.salience), "provenance": item.provenance},
                 persona_id=persona.public_id,
                 run_id=m.run.public_id if m.run else None)
        return result


def _add_source(item: MemoryItem, m: MemoryInput, conf: float, now: datetime) -> None:
    MemorySource.objects.create(
        memory=item, source_kind=m.source_kind.value, run=m.run,
        source_ref=(m.source_ref or m.source_event_id or "")[:500],
        observed_at=m.event_time or now, confidence=_d(conf),
    )


def _active_claims(persona, assertion):
    subject, predicate, _ = assertion
    return MemoryItem.objects.filter(
        persona=persona, assertion_subject=subject, assertion_predicate=predicate,
        status__in=[E.MemoryStatus.ACTIVE.value, E.MemoryStatus.PINNED.value],
    )


def _resolve(persona, new: MemoryItem, m: MemoryInput, now: datetime, result: WriteResult):
    """Memory v0.1 §10.1 — ista tvrdnja, druga vrednost."""
    for old in _active_claims(persona, m.assertion).exclude(pk=new.pk):
        explicit = (m.provenance == E.Provenance.USER_PROVIDED
                    and m.source_kind == E.SourceKind.FIRST_PARTY_USER_INPUT)
        stronger = float(new.confidence) >= float(old.confidence) - SUPERSEDE_TOLERANCE
        wins = old.status != E.MemoryStatus.PINNED.value and (explicit or stronger)
        c = MemoryContradiction.objects.create(
            persona=persona, left=old, right=new, detected_at=now, detector="rule:assertion",
            status="RESOLVED" if wins else "OPEN",
            resolution=("nova tvrdnja: " + ("eksplicitna potvrda" if explicit else
                        "jednaka ili jača pouzdanost")) if wins else
                       "nedovoljno dokaza — obe ostaju, kontekst ih označava",
            resolved_memory=new if wins else None, resolved_at=now if wins else None,
        )
        result.contradictions.append(c)
        if wins:
            old.status = E.MemoryStatus.SUPERSEDED.value
            old.superseded_by = new
            old.valid_to = now
            old.save(update_fields=["status", "superseded_by", "valid_to", "updated_at"])
            MemoryLink.objects.get_or_create(from_memory=new, to_memory=old,
                                             relation=E.MemoryRelation.SUPERSEDES.value)
            result.superseded.append(old)
        bus.emit("memory.contradiction_detected",
                 {"memory_id": str(new.id), "conflicting_memory_id": str(old.id),
                  "field": m.assertion[1]},
                 persona_id=persona.public_id,
                 run_id=m.run.public_id if m.run else None)
