"""Memorija i kontekst. Canon §8.2, §10; Memory v0.1 §13.

    POST /api/v1/personas/{public_id}/memories          upis (Idempotency-Key)
    POST /api/v1/personas/{public_id}/memories/query    hibridna pretraga, sa razlaganjem skora
    POST /api/v1/context/build                          context pack za run (Idempotency-Key)
    POST /api/v1/memories/{id}/supersede                nova verzija, stara ostaje kao istorija

Memorija nosi identitet persone i sme da sadrži osetljivo, zato je ne
čita `viewer`. Upis je posao onoga ko upravlja personom.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers

from api import audit
from api.base import AUDIT_READERS, PERSONA_WRITERS, PersonaOSView, ok
from api.errors import ApiError
from api.idempotency import idempotent
from api.views.personas import _get_persona
from apps.memory import context, retrieval
from apps.memory.models import MemoryItem, MemoryLink
from apps.memory.writer import MemoryInput, MemoryRejected, write
from apps.orchestration.models import AgentRun
from common import enums as E


def memory_out(m: MemoryItem) -> dict:
    return {
        "memory_id": str(m.id),
        "persona_id": m.persona.public_id,
        "memory_type": m.memory_type,
        "status": m.status,
        "provenance": m.provenance,
        "title": m.title,
        "content": m.content,
        "salience": str(m.salience),
        "confidence": str(m.confidence),
        "sensitivity": str(m.sensitivity),
        "tags": m.tags or [],
        "assertion": ({"subject": m.assertion_subject, "predicate": m.assertion_predicate,
                       "value": m.assertion_value} if m.assertion_predicate else None),
        "event_time": m.event_time.isoformat().replace("+00:00", "Z") if m.event_time else None,
        "valid_to": m.valid_to.isoformat().replace("+00:00", "Z") if m.valid_to else None,
        "superseded_by": str(m.superseded_by_id) if m.superseded_by_id else None,
    }


class AssertionIn(serializers.Serializer):
    subject = serializers.CharField(max_length=220)
    predicate = serializers.CharField(max_length=120)
    value = serializers.JSONField()


class MemoryIn(serializers.Serializer):
    memory_type = serializers.ChoiceField(choices=E.MemoryType.values())
    content = serializers.CharField(max_length=8000)
    title = serializers.CharField(max_length=220, required=False, default="")
    salience = serializers.FloatField(min_value=0, max_value=1, required=False, default=0.6)
    confidence = serializers.FloatField(min_value=0, max_value=1, required=False)
    sensitivity = serializers.FloatField(min_value=0, max_value=1, required=False, default=0)
    source_kind = serializers.ChoiceField(choices=E.SourceKind.values(), required=False,
                                          default=E.SourceKind.FIRST_PARTY_USER_INPUT.value)
    provenance = serializers.ChoiceField(choices=E.Provenance.values(), required=False,
                                         default=E.Provenance.USER_PROVIDED.value)
    tags = serializers.ListField(child=serializers.CharField(max_length=60), required=False,
                                 default=list, max_length=20)
    assertion = AssertionIn(required=False)
    pinned = serializers.BooleanField(required=False, default=False)


class QueryIn(serializers.Serializer):
    query = serializers.CharField(max_length=2000, allow_blank=True)
    profile = serializers.ChoiceField(choices=E.RetrievalProfile.values(), required=False,
                                      default=E.RetrievalProfile.RESEARCH.value)
    memory_types = serializers.ListField(child=serializers.ChoiceField(
        choices=E.MemoryType.values()), required=False, default=list)
    top_k = serializers.IntegerField(min_value=1, max_value=100, required=False)


class ContextIn(serializers.Serializer):
    persona_id = serializers.CharField()
    run_id = serializers.CharField()
    profile = serializers.ChoiceField(choices=E.RetrievalProfile.values())
    query = serializers.CharField(max_length=4000, required=False, default="", allow_blank=True)
    max_tokens = serializers.IntegerField(min_value=200, max_value=32000, required=False)


class SupersedeIn(serializers.Serializer):
    content = serializers.CharField(max_length=8000)
    title = serializers.CharField(max_length=220, required=False)
    reason = serializers.CharField(max_length=500)


def _write(persona, m: MemoryInput):
    try:
        return write(persona, m)
    except MemoryRejected as exc:
        raise ApiError(E.ErrorCode.VALIDATION_ERROR, str(exc), {"code": exc.code}) from exc


def _result_out(res) -> dict:
    return {
        "outcome": res.outcome,
        "reason": res.reason or None,
        "eligibility": res.eligibility,
        "memory": memory_out(res.memory) if res.memory else None,
        "superseded": [str(m.id) for m in res.superseded],
        "contradictions": [{"id": str(c.id), "status": c.status} for c in res.contradictions],
    }


class MemoryCreateView(PersonaOSView):
    required_roles = {"POST": PERSONA_WRITERS}

    @extend_schema(operation_id="memories_create", request=MemoryIn, responses={201: dict})
    @idempotent
    def post(self, request, public_id: str):
        p = _get_persona(public_id)
        data = MemoryIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        a = v.get("assertion")
        with transaction.atomic():
            res = _write(p, MemoryInput(
                memory_type=E.MemoryType(v["memory_type"]), content=v["content"],
                title=v["title"], salience=v["salience"], confidence=v.get("confidence"),
                sensitivity=v["sensitivity"], source_kind=E.SourceKind(v["source_kind"]),
                provenance=E.Provenance(v["provenance"]), tags=v["tags"],
                assertion=(a["subject"], a["predicate"], a["value"]) if a else None,
                status=E.MemoryStatus.PINNED if v["pinned"] else E.MemoryStatus.ACTIVE,
            ))
            if res.memory is not None:
                audit.record(f"api.memory.{res.outcome}", persona=p,
                             after={"memory_id": str(res.memory.id)},
                             details={"memory_type": v["memory_type"],
                                      "superseded": [str(m.id) for m in res.superseded]})
        return ok(_result_out(res), status=201 if res.outcome == "created" else 200)


class MemoryQueryView(PersonaOSView):
    required_roles = {"POST": AUDIT_READERS}

    @extend_schema(operation_id="memories_query", request=QueryIn, responses={200: dict})
    def post(self, request, public_id: str):
        p = _get_persona(public_id)
        data = QueryIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        scored = retrieval.retrieve(
            p, v["query"], E.RetrievalProfile(v["profile"]), top_k=v.get("top_k"),
            memory_types=[E.MemoryType(t) for t in v["memory_types"]] or None)
        return ok([{"score": s.score, "why": s.breakdown, "contested": s.contested,
                    "memory": memory_out(s.memory)} for s in scored])


class ContextBuildView(PersonaOSView):
    required_roles = {"POST": AUDIT_READERS}

    @extend_schema(operation_id="context_build", request=ContextIn, responses={201: dict})
    @idempotent
    def post(self, request):
        data = ContextIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        p = _get_persona(v["persona_id"])
        run = AgentRun.objects.filter(public_id=v["run_id"], persona=p).first()
        if run is None:
            raise ApiError(E.ErrorCode.NOT_FOUND, "Run ne postoji za ovu personu.")
        pack = context.build(p, run, E.RetrievalProfile(v["profile"]), query=v["query"],
                             max_tokens=v.get("max_tokens"))
        r = pack.record
        return ok({"pack_id": str(r.id), "run_id": run.public_id, "purpose": r.purpose,
                   "token_count": r.token_count, "truncated": r.truncated,
                   "pack_hash": r.pack_hash, "memory_ids": r.memory_ids,
                   "scores": r.scores, "text": pack.text}, status=201)


class MemorySupersedeView(PersonaOSView):
    required_roles = {"POST": PERSONA_WRITERS}

    @extend_schema(operation_id="memories_supersede", request=SupersedeIn, responses={201: dict})
    @idempotent
    def post(self, request, memory_id: str):
        try:
            old = MemoryItem.objects.select_related("persona").get(id=uuid.UUID(memory_id))
        except (ValueError, MemoryItem.DoesNotExist):
            raise ApiError(E.ErrorCode.NOT_FOUND, "Memorija ne postoji.") from None
        if old.status not in (E.MemoryStatus.ACTIVE.value, E.MemoryStatus.PINNED.value):
            raise ApiError(E.ErrorCode.VERSION_CONFLICT,
                           f"Memorija je {old.status} — zameniti se može samo aktivna.",
                           {"status": old.status})
        data = SupersedeIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        now = timezone.now()
        with transaction.atomic():
            res = _write(old.persona, MemoryInput(
                memory_type=E.MemoryType(old.memory_type), content=v["content"],
                title=v.get("title", old.title), salience=float(old.salience),
                source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT,
                provenance=E.Provenance.USER_PROVIDED, tags=old.tags or [],
                assertion=((old.assertion_subject, old.assertion_predicate, v["content"])
                           if old.assertion_predicate else None),
            ))
            new = res.memory
            if new is None or new.pk == old.pk:
                raise ApiError(E.ErrorCode.VALIDATION_ERROR,
                               "Nova verzija je ista kao stara ili nije prošla prag upisa.",
                               {"outcome": res.outcome})
            old.refresh_from_db()
            if old.status != E.MemoryStatus.SUPERSEDED.value:
                old.status, old.superseded_by, old.valid_to = (
                    E.MemoryStatus.SUPERSEDED.value, new, now)
                old.save(update_fields=["status", "superseded_by", "valid_to", "updated_at"])
                MemoryLink.objects.get_or_create(from_memory=new, to_memory=old,
                                                 relation=E.MemoryRelation.SUPERSEDES.value)
            audit.record("api.memory.superseded", persona=old.persona,
                         before={"memory_id": str(old.id)}, after={"memory_id": str(new.id)},
                         details={"reason": v["reason"]})
        return ok({"memory": memory_out(new), "superseded": str(old.id)}, status=201)
