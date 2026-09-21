"""World Engine: prijem, dedup i rutiranje događaja. Behaviour v0.1 §10–§12.

World Engine ne odlučuje šta persona radi — samo zapisuje „šta se desilo"
i kome bi moglo biti važno. Odluka ostaje engine-u pri buđenju.

Relevantnost (§12) se računa jeftino, pre ikakvog LLM-a. Od sedam signala
iz formule, u F3 postoje tri: preklapanje tema (tagovi persone kategorije
`niche`), geografija i svežina. Ostali — cilj, odnos, novina iz memorije,
jačina interesovanja — dolaze sa F4 (memorija) i Social Graph-om. Da pragovi
0.28 / 0.52 ostanu smisleni, zbir se deli zbirom težina signala koji
postoje (ADR-0005). Kad signal stigne, dodaje se ovde i imenilac raste.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.behaviour.models import WorldEvent
from apps.observability import bus
from apps.personas.models import Persona, PersonaTagLink
from common import enums as E
from common import ids as I

#: Behaviour v0.1 §12 — težine signala koji postoje u F3.
WEIGHTS = {"topic_overlap": 0.30, "geographic_match": 0.12, "recency": 0.10}
#: Jedan događaj ne sme odjednom da probudi više od ovoliko persona (§21 burst cap).
FANOUT_CAP = 50


@dataclass(frozen=True)
class Route:
    persona_public_id: str
    relevance: float
    outcome: str  # ignore / store_only / wake


def _persona_geo(p: Persona) -> set[str]:
    region = (p.primary_locale.split("-")[-1] if "-" in p.primary_locale else "").upper()
    return {region} if len(region) == 2 else set()


def relevance(p: Persona, topics: list[str], geo: list[str], occurred_at: datetime,
              expires_at: datetime | None, now: datetime, interests: dict[str, float]) -> float:
    topics = [t.lower() for t in topics]
    overlap = max((interests.get(t, 0.0) for t in topics), default=0.0)
    geo_match = 1.0 if (_persona_geo(p) & {g.upper() for g in geo}) else 0.0
    ttl = (expires_at - occurred_at) if expires_at else timedelta(days=2)
    age = max(now - occurred_at, timedelta(0))
    recency = max(0.0, 1.0 - age / ttl) if ttl.total_seconds() > 0 else 0.0
    score = (WEIGHTS["topic_overlap"] * overlap + WEIGHTS["geographic_match"] * geo_match
             + WEIGHTS["recency"] * recency) / sum(WEIGHTS.values())
    return round(score, 4)


def _interests(p: Persona) -> dict[str, float]:
    return {
        link.tag.slug: float(link.weight)
        for link in PersonaTagLink.objects.filter(
            persona=p, tag__category="niche"
        ).select_related("tag")
    }


def ingest(*, event_type: str, topics: list[str], geo: list[str] | None = None,
           occurred_at: datetime | None = None, expires_at: datetime | None = None,
           source: str, dedupe_key: str | None = None, payload: dict | None = None,
           now: datetime | None = None,
           statuses: frozenset[E.PersonaStatus] = E.WAKEABLE_BY_SCHEDULER,
           ) -> tuple[WorldEvent | None, list[Route]]:
    """Upiši događaj i rutiraj ga. Duplikat (isti `dedupe_key`) vraća (None, [])."""
    now = now or timezone.now()
    occurred_at = occurred_at or now
    geo = geo or []
    try:
        with transaction.atomic():
            ev = WorldEvent.objects.create(
                public_id=I.ulid_public_id(I.EntityKind.WORLD_EVENT, occurred_at),
                event_type=event_type, scope=E.ScopeKind.GLOBAL.value,
                occurred_at=occurred_at, available_at=now, expires_at=expires_at,
                provenance=E.Provenance.OBSERVED.value,
                payload={"topics": topics, "geo": geo, "source": source, **(payload or {})},
                dedupe_key=dedupe_key,
            )
            bus.emit("world.event.created", {"source": source, "kind": event_type},
                     persona_id=None)
    except IntegrityError:
        return None, []

    routes: list[Route] = []
    woken = 0
    personas = Persona.objects.filter(status__in=[s.value for s in statuses])
    for p in personas.order_by("public_id"):
        r = relevance(p, topics, geo, occurred_at, expires_at, now, _interests(p))
        if r < E.WORLD_RELEVANCE_IGNORE_BELOW:
            routes.append(Route(p.public_id, r, "ignore"))
        elif r < E.WORLD_RELEVANCE_WAKE_FROM or woken >= FANOUT_CAP:
            routes.append(Route(p.public_id, r, "store_only"))
        else:
            woken += 1
            routes.append(Route(p.public_id, r, "wake"))
    return ev, routes


def pending_wakes(routes: list[Route]) -> list[Route]:
    return [r for r in routes if r.outcome == "wake"]

