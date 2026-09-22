"""Pouke urednika — persona uči iz odbijanja i izmena (ADR-0014).

Svaka odluka urednika sa razlogom ili izmenom postaje kratko pravilo koje ide
u svaki sledeći prompt za pisanje. Dva nivoa:

  - pouka jedne persone (`persona` popunjena);
  - kućni stil organizacije (`persona` prazna) — važi za sve persone, i za
    one koje tek nastaju.

Pouka nije memorija: ne bledi i ne zavisi od retrieval-a. Zato se u prompt
stavlja doslovno, ograničena brojem, a urednik je gasi kad prestane da važi.
"""

from __future__ import annotations

import difflib
import re

from django.db.models import Q

from api import audit
from apps.content.models import EditorialLesson
from apps.personas.models import Persona

#: Koliko pouka ide u prompt — po nivou. Najnovije prve.
PROMPT_LIMIT_PERSONA = 10
PROMPT_LIMIT_GLOBAL = 10
_EXCERPT = 120


def _tokens(text: str) -> list[str]:
    return re.findall(r"\S+|\n", text)


def _clip(words: list[str]) -> str:
    s = " ".join(w for w in words if w != "\n").strip()
    return s if len(s) <= _EXCERPT else s[: _EXCERPT - 1] + "…"


def describe_edit(before: str, after: str, *, max_ops: int = 3) -> str:
    """Rečima opisuje šta je urednik promenio — bez modela, deterministički."""
    a, b = _tokens(before), _tokens(after)
    ops: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        old, new = _clip(a[i1:i2]), _clip(b[j1:j2])
        if tag == "equal" or (not old and not new):
            continue
        if tag == "replace" and old and new:
            ops.append(f"«{old}» → «{new}»")
        elif old:
            ops.append(f"ukloni «{old}»")
        else:
            ops.append(f"dodaj «{new}»")
        if len(ops) >= max_ops:
            break
    return "; ".join(ops)


def learn(*, persona: Persona, kind: str, actor: str, reason: str = "", before: str = "",
          after: str = "", everyone: bool = False, source_action=None) -> EditorialLesson | None:
    """Pravi pouku iz odluke. Vraća None kad nema šta da se nauči."""
    reason = (reason or "").strip()
    if kind == "edited":
        change = describe_edit(before, after)
        if not change and not reason:
            return None
        text = reason or f"Urednik je ispravio tekst: {change}. Ne ponavljaj isto."
        ex_before, ex_after = before[:300], after[:300]
    elif kind == "rejected":
        if not reason:
            return None
        text, ex_before, ex_after = f"Urednik je odbio nacrt: {reason}", before[:300], ""
    else:
        if not reason:
            return None
        text, ex_before, ex_after = reason, "", ""
    target = None if everyone else persona
    dup = EditorialLesson.objects.filter(persona=target, text=text[:500], is_active=True).first()
    if dup:
        return dup
    lesson = EditorialLesson.objects.create(
        persona=target, kind=kind, text=text[:500], example_before=ex_before,
        example_after=ex_after, source_action=source_action, created_by=actor[:120])
    audit.record("content.lesson.learned", persona=persona,
                 details={"lesson_id": str(lesson.id), "kind": kind,
                          "scope": "all" if everyone else persona.public_id})
    return lesson


def active_for(persona: Persona) -> tuple[list[EditorialLesson], list[EditorialLesson]]:
    """(kućni stil, pouke persone) — aktivne, najnovije prve, sa plafonom."""
    qs = EditorialLesson.objects.filter(is_active=True).order_by("-created_at")
    return (list(qs.filter(persona__isnull=True)[:PROMPT_LIMIT_GLOBAL]),
            list(qs.filter(persona=persona)[:PROMPT_LIMIT_PERSONA]))


def prompt_section(persona: Persona) -> str:
    org, own = active_for(persona)
    if not org and not own:
        return ""
    lines = ["## pouke urednika (obavezno poštuj; novije imaju prednost)"]
    lines += [f"- [svi] {x.text}" for x in org]
    lines += [f"- {x.text}" for x in own]
    return "\n".join(lines)


def visible(persona: Persona):
    return (EditorialLesson.objects.filter(Q(persona=persona) | Q(persona__isnull=True))
            .order_by("-is_active", "-created_at"))
