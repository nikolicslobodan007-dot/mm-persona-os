"""Životni ciklus memorije: konsolidacija, bleđenje, istek, brisanje.
Memory v0.1 §8, §9, §14; Canon §10.3.

  - `consolidate_day` — epizode jednog lokalnog dana postaju jedan dnevni
    zapis. Originali se ARHIVIRAJU (ne brišu) i ostaju povezani vezom
    `derived`, pa se svaka rečenica sažetka može pratiti do izvora (§9).
    Sažetak je deterministički — sastavljen iz podataka, ne iz LLM-a;
    LLM sažimanje dolazi sa gateway-om i mora da sačuva iste veze.
  - `expire_working` — radna memorija živi do `expires_at` (6 h).
  - `apply_decay` — memorija čija efektivna važnost padne ispod 0.05 se
    arhivira. Osnovna `salience` se ne menja; bledi samo efektivna.
  - `forget` — brisanje sa propagacijom (§15): sadržaj se prepisuje,
    vektori i veze se uklanjaju, red ostaje kao nadgrobni zapis (DELETED)
    da bi audit i dalje znao da je nešto postojalo.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.memory import embeddings, retrieval
from apps.memory.models import MemoryEmbedding, MemoryItem, MemoryLink, MemorySource
from apps.memory.writer import MemoryInput, embed_memory, write
from apps.observability import bus
from apps.orchestration.models import AgentRun
from common import enums as E

#: Epizoda ovolike važnosti je „prekretnica" i ostaje aktivna posle konsolidacije.
MILESTONE_SALIENCE = 0.80


def _day_bounds(d: date, tz: str) -> tuple[datetime, datetime]:
    z = ZoneInfo(tz)
    start = datetime.combine(d, time(0, 0), tzinfo=z)
    utc = ZoneInfo("UTC")
    return start.astimezone(utc), (start + timedelta(days=1)).astimezone(utc)


def consolidate_day(persona, d: date, *, now: datetime | None = None) -> MemoryItem | None:
    now = now or timezone.now()
    start, end = _day_bounds(d, persona.timezone)
    episodes = list(MemoryItem.objects.filter(
        persona=persona, memory_type=E.MemoryType.EPISODIC.value,
        status=E.MemoryStatus.ACTIVE.value, event_time__gte=start, event_time__lt=end,
    ).exclude(source_event_id__startswith="consolidation:").order_by("event_time"))
    runs = list(AgentRun.objects.filter(persona=persona, started_at__gte=start,
                                        started_at__lt=end).values_list("decision", "summary_json"))
    if not episodes and not runs:
        return None

    decisions = Counter(dec for dec, _ in runs if dec)
    acts = Counter((s or {}).get("activity") for dec, s in runs if dec == "ACT")
    topics = Counter(t for e in episodes for t in (e.tags or []))
    lines = [f"Buđenja: {sum(decisions.values())} — " + ", ".join(
        f"{k} {v}" for k, v in sorted(decisions.items()))] if decisions else []
    if acts:
        lines.append("Aktivnosti: " + ", ".join(f"{k} {v}" for k, v in sorted(acts.items()) if k))
    if topics:
        lines.append("Teme: " + ", ".join(t for t, _ in topics.most_common(5)))
    lines += [f"• {e.title or e.content[:120]}" for e in episodes[:20]]

    with transaction.atomic():
        res = write(persona, MemoryInput(
            memory_type=E.MemoryType.EPISODIC, title=f"Dan {d.isoformat()}",
            content="\n".join(lines), source_kind=E.SourceKind.SYSTEM_OBSERVATION,
            provenance=E.Provenance.OBSERVED,
            salience=max([float(e.salience) for e in episodes] + [0.4]),
            novelty=0.3, future_utility=0.6, tags=[t for t, _ in topics.most_common(5)],
            event_time=end - timedelta(seconds=1),
            source_event_id=f"consolidation:daily:{d.isoformat()}",
        ), now=now)
        summary = res.memory
        if res.outcome != "created" or summary is None:
            return summary
        archived = 0
        for e in episodes:
            MemoryLink.objects.get_or_create(from_memory=summary, to_memory=e,
                                             relation=E.MemoryRelation.DERIVED.value)
            if float(e.salience) < MILESTONE_SALIENCE:
                e.status = E.MemoryStatus.ARCHIVED.value
                e.save(update_fields=["status", "updated_at"])
                archived += 1
        bus.emit("memory.consolidated",
                 {"job": "daily", "items_in": len(episodes), "items_out": 1},
                 persona_id=persona.public_id)
    return summary


def expire_working(persona, now: datetime | None = None) -> int:
    now = now or timezone.now()
    return MemoryItem.objects.filter(
        persona=persona, memory_type=E.MemoryType.WORKING.value,
        status=E.MemoryStatus.ACTIVE.value, expires_at__lte=now,
    ).update(status=E.MemoryStatus.ARCHIVED.value, updated_at=now)


def apply_decay(persona, now: datetime | None = None) -> int:
    now = now or timezone.now()
    faded = [m.pk for m in MemoryItem.objects.filter(
        persona=persona, status=E.MemoryStatus.ACTIVE.value).only(
        "salience", "memory_type", "event_time", "created_at", "status")
        if retrieval.effective_salience(m, now) < E.ARCHIVE_BELOW_EFFECTIVE_SALIENCE]
    if faded:
        MemoryItem.objects.filter(pk__in=faded).update(
            status=E.MemoryStatus.ARCHIVED.value, updated_at=now)
    return len(faded)


def forget(memory: MemoryItem, *, reason: str) -> None:
    """Memory v0.1 §15 — brisanje propagira na vektor, veze i izvore."""
    with transaction.atomic():
        MemoryEmbedding.objects.filter(memory=memory).delete()
        MemoryLink.objects.filter(from_memory=memory).delete()
        MemoryLink.objects.filter(to_memory=memory).delete()
        MemorySource.objects.filter(memory=memory).update(source_ref="")
        memory.title = ""
        memory.content = f"[obrisano: {reason[:80]}]"
        memory.assertion_value = None
        memory.tags = []
        memory.status = E.MemoryStatus.DELETED.value
        memory.save()


def reindex(persona=None) -> int:
    """Izračunaj vektore koji fale za trenutni model (npr. posle promene modela)."""
    qs = MemoryItem.objects.exclude(status=E.MemoryStatus.DELETED.value)
    if persona is not None:
        qs = qs.filter(persona=persona)
    n = 0
    for m in qs.iterator():
        if not m.content_hash:
            m.content_hash = embeddings.text_hash(f"{m.title}\n{m.content}")
            m.save(update_fields=["content_hash"])
        embed_memory(m)
        n += 1
    return n
