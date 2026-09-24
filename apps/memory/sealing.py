"""Pečaćenje memorije — kompresija u nivoe i zajedničko znanje. ADR-0020.

Problem koji ovo rešava: agent koji radi mesecima nakupi hiljade zapisa, a u
prompt staje nekoliko. Retrieval bira najbolje, ali bira **među sve više
kandidata** i stari zapisi se tiho gube. Na 10.000 agenata isto znanje se uz to
otkriva iznova u svakom agentu.

Rešenje je kaskada, ista ona koju već koristi dnevna konsolidacija:

    12 zapisa jednog agenta o jednoj temi  → sažetak nivoa 1 (agent)
     5 takvih sažetaka iz istog sektora    → sažetak sektora
     5 sažetaka sektora o istoj temi       → sažetak firme

Tri pravila:

  - **Sažetak je deterministički**, sastavljen od podataka, ne od modela. Isti
    ulaz daje isti izlaz, a svaka stavka ima vezu `DERIVED` do izvora.
  - **Peča se samo ono što se ponavlja.** Tema ispod praga se ne dira; struktura
    se ne gradi unapred (ADR-0020, obrazac preuzet iz OpenHuman Memory Tree).
  - **Zajednička memorija se ne upisuje direktno**, nego samo nastaje
    pečaćenjem naviše. Inače se za mesec dana pretvori u smetlište.

Izvori ostaju: arhiviraju se, ne brišu, pa se svaka rečenica sažetka prati
unazad do zapisa iz kog je nastala.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.memory.models import MemoryItem, MemoryLink
from apps.memory.writer import MemoryInput, write
from apps.observability import bus
from apps.personas.models import Department, Persona
from common import enums as E

S = E.MemoryScope

#: Koliko zapisa o jednoj temi pokreće pečaćenje, po nivou.
SEAL_AT_PERSONA = 12
SEAL_AT_DEPARTMENT = 5
SEAL_AT_COMPANY = 5
#: Koliko stavki ulazi u sam tekst sažetka (ostale se broje, ne prepisuju).
BULLETS = 12
#: Prekretnica ostaje aktivna i posle pečaćenja — isto pravilo kao kod
#: dnevne konsolidacije (Memory v0.1 §9).
MILESTONE_SALIENCE = 0.80
#: Radna memorija ističe sama; epizode hvata dnevna konsolidacija.
SEALABLE = (E.MemoryType.SEMANTIC.value, E.MemoryType.CONTENT.value,
            E.MemoryType.PROCEDURAL.value, E.MemoryType.SOCIAL.value)


def topic_of(m: MemoryItem) -> str:
    """Tema je prva oznaka zapisa; bez oznaka ide u zajedničku korpu."""
    tags = m.tags or []
    return str(tags[0]).strip().lower()[:80] if tags else "ostalo"


def _key(scope: str, topic: str, level: int, owner: str) -> str:
    raw = f"{scope}:{owner}:{topic}:{level}"
    return f"seal:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def _summary_text(topic: str, items: list[MemoryItem]) -> str:
    head = f"Sažetak teme „{topic}” — {len(items)} zapisa."
    lines = [f"• {m.title or m.content[:120]}" for m in items[:BULLETS]]
    if len(items) > BULLETS:
        lines.append(f"• …i još {len(items) - BULLETS} zapisa istog smera.")
    return "\n".join([head, *lines])


@transaction.atomic
def _make(persona: Persona, items: list[MemoryItem], *, topic: str, scope: str,
          level: int, department: Department | None, owner: str,
          now: datetime) -> MemoryItem | None:
    """Pravi jedan sažetak i arhivira izvore. Idempotentno po `source_event_id`."""
    res = write(persona, MemoryInput(
        memory_type=E.MemoryType.SEMANTIC,
        title=f"Sažetak: {topic}" + ("" if scope == S.PERSONA.value else f" ({scope})"),
        content=_summary_text(topic, items),
        source_kind=E.SourceKind.SYSTEM_OBSERVATION, provenance=E.Provenance.OBSERVED,
        salience=max(float(m.salience) for m in items),
        novelty=0.2, future_utility=0.8, tags=[topic],
        event_time=now, source_event_id=_key(scope, topic, level, owner),
    ), now=now)
    summary = res.memory
    if summary is None or res.outcome != "created":
        return summary
    MemoryItem.objects.filter(pk=summary.pk).update(
        scope=scope, department=department, level=level)
    for m in items:
        MemoryLink.objects.get_or_create(from_memory=summary, to_memory=m,
                                         relation=E.MemoryRelation.DERIVED.value)
        if float(m.salience) < MILESTONE_SALIENCE and m.status != E.MemoryStatus.PINNED.value:
            MemoryItem.objects.filter(pk=m.pk).update(
                status=E.MemoryStatus.ARCHIVED.value, updated_at=now)
    bus.emit("memory.consolidated",
             {"job": f"seal:{scope}", "items_in": len(items), "items_out": 1},
             persona_id=persona.public_id)
    summary.refresh_from_db()
    return summary


def _buckets(qs, level: int) -> dict[str, list[MemoryItem]]:
    out: dict[str, list[MemoryItem]] = defaultdict(list)
    for m in qs.filter(level=level, status=E.MemoryStatus.ACTIVE.value,
                       memory_type__in=SEALABLE).order_by("created_at"):
        out[topic_of(m)].append(m)
    return out


def seal_persona(persona: Persona, *, now: datetime | None = None,
                 threshold: int | None = None) -> list[MemoryItem]:
    """Peča memoriju jednog agenta, nivo po nivo, dok ima prepunih tema."""
    now = now or timezone.now()
    limit = threshold or SEAL_AT_PERSONA
    made: list[MemoryItem] = []
    qs = MemoryItem.objects.filter(persona=persona, scope=S.PERSONA.value)
    level = 0
    while level < 5:
        for topic, items in _buckets(qs, level).items():
            if len(items) < limit:
                continue
            m = _make(persona, items, topic=topic, scope=S.PERSONA.value, level=level + 1,
                      department=None, owner=persona.public_id, now=now)
            if m is not None:
                made.append(m)
        level += 1
    return made


def seal_department(department: Department, *, now: datetime | None = None,
                    threshold: int | None = None) -> list[MemoryItem]:
    """Znanje koje se ponavlja kod više agenata istog sektora postaje sektorsko."""
    from apps.personas.org import position_of

    now = now or timezone.now()
    limit = threshold or SEAL_AT_DEPARTMENT
    people = [p for p in Persona.objects.exclude(status=E.PersonaStatus.ARCHIVED.value)
              if (pos := position_of(p)) is not None and pos.department_id == department.pk]
    if not people:
        return []
    qs = MemoryItem.objects.filter(persona__in=people, scope=S.PERSONA.value,
                                   level__gte=1)
    made: list[MemoryItem] = []
    for topic, items in _buckets(qs, 1).items():
        if len(items) < limit:
            continue
        author = items[-1].persona
        m = _make(author, items, topic=topic, scope=S.DEPARTMENT.value, level=1,
                  department=department, owner=department.code, now=now)
        if m is not None:
            made.append(m)
    return made


def seal_company(*, now: datetime | None = None,
                 threshold: int | None = None) -> list[MemoryItem]:
    """Tema koja se ponavlja u više sektora postaje znanje cele firme."""
    now = now or timezone.now()
    limit = threshold or SEAL_AT_COMPANY
    qs = MemoryItem.objects.filter(scope=S.DEPARTMENT.value)
    made: list[MemoryItem] = []
    for topic, items in _buckets(qs, 1).items():
        if len({m.department_id for m in items}) < 2 or len(items) < limit:
            continue
        m = _make(items[-1].persona, items, topic=topic, scope=S.COMPANY.value, level=2,
                  department=None, owner="firma", now=now)
        if m is not None:
            made.append(m)
    return made


def seal_all(*, now: datetime | None = None) -> dict[str, int]:
    """Cela kaskada, odozdo naviše. Vraća broj napravljenih sažetaka po nivou."""
    now = now or timezone.now()
    stats = {"agent": 0, "sektor": 0, "firma": 0}
    for p in Persona.objects.exclude(status=E.PersonaStatus.ARCHIVED.value):
        stats["agent"] += len(seal_persona(p, now=now))
    for d in Department.objects.filter(is_active=True):
        stats["sektor"] += len(seal_department(d, now=now))
    stats["firma"] += len(seal_company(now=now))
    return stats


def counts(persona: Persona) -> dict[str, int]:
    """Za konzolu: koliko čega agent vidi."""
    from apps.personas.org import department_of

    dep = department_of(persona)
    own = MemoryItem.objects.filter(persona=persona, scope=S.PERSONA.value,
                                    status=E.MemoryStatus.ACTIVE.value)
    return {
        "svoje": own.filter(level=0).count(),
        "sažeci": own.filter(level__gte=1).count(),
        "sektor": MemoryItem.objects.filter(scope=S.DEPARTMENT.value, department=dep,
                                            status=E.MemoryStatus.ACTIVE.value).count()
        if dep else 0,
        "firma": MemoryItem.objects.filter(scope=S.COMPANY.value,
                                           status=E.MemoryStatus.ACTIVE.value).count(),
    }
