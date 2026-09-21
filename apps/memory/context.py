"""Context Builder. Memory v0.1 §12; Canon §1, §10.4, §16.3.

    pack = build(persona, run, RetrievalProfile.DAILY_PLANNER, query="…")

Pravi najmanji skup informacija za jednu odluku i beleži TAČNO šta je
ušlo (`MemoryContextPack`: ID-jevi, skorovi, hash). Tekst se ne čuva u
paketu — rekonstruiše se iz memorija i poredi sa hash-om.

Pravila iz §12.2 koja se ovde sprovode, ne preporučuju:
  - zamenjene (SUPERSEDED) tvrdnje nikad ne ulaze;
  - sporne (otvorena protivrečnost) ulaze samo sa oznakom „⚠ sporno";
  - izvod (`inferred`) ulazi sa oznakom „izvod, ne činjenica" (Canon §10.4);
  - osetljivo ulazi samo za dozvoljenu svrhu (filter je u retrieval-u);
  - tvrdi plafon tokena se nikad ne prelazi — višak se odseca i beleži.

Procena tokena je ⌈znakova / 4⌉ — gruba, ali konzervativna za latinicu.
Pravi tokenizer dolazi sa LLM gateway-om.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.behaviour.models import BehaviourState
from apps.memory import retrieval
from apps.memory.models import MemoryContextPack, MemoryItem
from apps.observability import bus
from apps.personas.models import Biography, TraitProfile
from common import enums as E

#: Memory v0.1 §12 — fiksni deo konteksta pored memorije.
CORE_OVERHEAD_TOKENS = 1500
POLICY_LINES = (
    "Spoljne akcije nisu dozvoljene bez odluke Policy engine-a (Canon §6.2).",
    "AI priroda persone se nikad ne skriva (Canon §9.4).",
    "Izvod (inferred) nije činjenica i ne ide u javni izlaz (Canon §10.4).",
)


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


@dataclass
class Pack:
    record: MemoryContextPack
    text: str
    sections: dict[str, str]
    items: list[retrieval.Scored] = field(default_factory=list)


def _core(persona) -> str:
    bio = Biography.objects.filter(persona=persona).first()
    traits = TraitProfile.objects.filter(persona=persona).first()
    lines = [f"{persona.display_name} [{persona.public_id}] — AI persona; oznaka je obavezna.",
             f"Jezik {persona.primary_locale}, vremenska zona {persona.timezone}."]
    if bio:
        lines.append(bio.headline or bio.short_bio[:300])
    if traits:
        top = sorted(((f, getattr(traits, f)) for f in (
            "openness", "conscientiousness", "extraversion", "curiosity",
            "evidence_preference", "risk_tolerance")), key=lambda x: -x[1])[:4]
        lines.append("Izražene osobine: " + ", ".join(f"{k} {v}" for k, v in top))
    return "\n".join(lines)


def _state(persona) -> str:
    s = BehaviourState.objects.filter(persona=persona).first()
    if not s:
        return ""
    return (f"energija {s.energy}, raspoloženje {s.valence}, fokus {s.focus}, "
            f"opterećenje {s.cognitive_load}, pažnja preostala {s.attention_remaining}")


def _line(sc: retrieval.Scored) -> str:
    m = sc.memory
    marks = []
    if sc.contested:
        marks.append("⚠ sporno")
    if m.provenance == E.Provenance.INFERRED.value:
        marks.append("izvod, ne činjenica")
    head = f"[{m.memory_type} · pouzdanost {m.confidence}" + (
        f" · {'; '.join(marks)}" if marks else "") + "]"
    body = f"{m.title}: {m.content}" if m.title else m.content
    return f"- {head} {body}"


def build(persona, run, profile: E.RetrievalProfile, *, query: str = "",
          max_tokens: int | None = None, now: datetime | None = None,
          memory_types: list[E.MemoryType] | None = None) -> Pack:
    now = now or timezone.now()
    budget = max_tokens or (E.PROFILE_MEMORY_TOKENS[profile] + CORE_OVERHEAD_TOKENS)
    sections = {
        "persona_core": _core(persona),
        "current_state": _state(persona),
        "task_goal": query,
        "policy_constraints": "\n".join(POLICY_LINES),
    }
    def render(secs: dict[str, str]) -> str:
        return "\n\n".join(f"## {k}\n{v}" for k, v in secs.items() if v)

    # Zaglavlje sekcije „retrieved_memory" košta i kad je prazna — zato +8.
    fixed = tokens(render(sections)) + 8
    if fixed > budget:  # predugačak upit ne sme da probije plafon
        keep = max(0, len(query) - (fixed - budget) * 4)
        sections["task_goal"] = query[:keep]
        fixed = tokens(render(sections)) + 8
    room = max(0, min(E.PROFILE_MEMORY_TOKENS[profile], budget - fixed))

    candidates = retrieval.retrieve(persona, query, profile, now=now, memory_types=memory_types)
    chosen: list[retrieval.Scored] = []
    lines: list[str] = []
    used = 0
    truncated = False
    for sc in candidates:
        line = _line(sc)
        t = tokens(line + "\n")
        if used + t > room:
            truncated = True
            continue
        chosen.append(sc)
        lines.append(line)
        used += t
    sections["retrieved_memory"] = "\n".join(lines)
    text = render(sections)
    total = tokens(text)

    with transaction.atomic():
        record = MemoryContextPack.objects.create(
            persona=persona, run=run, purpose=E.PROFILE_PURPOSE[profile].value,
            query_text=query, memory_ids=[str(s.memory.id) for s in chosen],
            scores={str(s.memory.id): {"R": s.score, **s.breakdown} for s in chosen},
            token_count=total, truncated=truncated,
            pack_hash=hashlib.sha256(text.encode()).hexdigest(), built_at=now,
        )
        MemoryItem.objects.filter(id__in=[s.memory.id for s in chosen]).update(
            recall_count=F("recall_count") + 1, last_recalled_at=now)
        bus.emit("context.built",
                 {"profile": profile.value, "item_count": len(chosen), "token_estimate": total},
                 persona_id=persona.public_id, run_id=run.public_id)
    return Pack(record, text, sections, chosen)
