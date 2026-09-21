"""Due resolver. Canon §11.1, Behaviour v0.1 §16–§17, §22.

Svakih 30 s jedan upit bira persone kojima ističe `next_wake_at` u narednih
90 s. `FOR UPDATE SKIP LOCKED` znači da dva beat-a ili dva workera nikada
ne izaberu istu personu; ona koju upravo računa `wake()` (drži bravu) se
preskače, ne čeka.

Izabranoj personi se `next_wake_at` odmah pomera za `CLAIM_SECONDS` — to je
„uzeo sam je". Ako se poruka izgubi (Redis restart, worker pad), persona se
vraća u izbor posle tog vremena: izvor istine je PostgreSQL, ne red (§22).
Ključ buđenja nosi originalni `due_at`, pa i dvostruka isporuka iste poruke
daje jedan run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction

from apps.behaviour.models import BehaviourState
from common import enums as E

CLAIM_SECONDS = 300


@dataclass(frozen=True)
class Due:
    persona_public_id: str
    due_at: datetime
    priority: E.WakePriority

    @property
    def wake_key(self) -> str:
        return f"sched|{self.persona_public_id}|{self.due_at.isoformat()}"


def _priority(value: int) -> E.WakePriority:
    for p, v in E.WAKE_PRIORITY_VALUE.items():
        if v == value:
            return p
    return E.WakePriority.ROUTINE_WINDOW


def scan_due(now: datetime, *, limit: int | None = None) -> list[Due]:
    lookahead = timedelta(seconds=settings.SCHEDULER_LOOKAHEAD_SECONDS)
    limit = limit or settings.SCHEDULER_BATCH_SIZE
    with transaction.atomic():
        rows = list(
            BehaviourState.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("persona")
            .filter(
                next_wake_at__lte=now + lookahead,
                persona__status__in=[s.value for s in E.WAKEABLE_BY_SCHEDULER],
            )
            .order_by("-wake_priority", "next_wake_at")[:limit]
        )
        out = [Due(r.persona.public_id, r.next_wake_at, _priority(r.wake_priority)) for r in rows]
        if rows:
            BehaviourState.objects.filter(pk__in=[r.pk for r in rows]).update(
                next_wake_at=now + timedelta(seconds=CLAIM_SECONDS)
            )
    return out
