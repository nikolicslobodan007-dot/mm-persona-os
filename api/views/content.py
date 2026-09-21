"""Sadržaj. Canon §8.2 · ADR-0009.

    GET  /api/v1/content/items                     nacrti i objave (filter persona/status)
    POST /api/v1/content/items                     nacrt: tema (model) ili tekst (čovek)
    GET  /api/v1/content/items/{id}                jedan komad sa objavama
    POST /api/v1/content/items/{id}/schedule       predlog objave na nalog → policy → odobrenje

Nacrt nema spoljni efekat. `schedule` je jedini put do objave i uvek ide kroz
policy; javna objava uvek traži odobrenje (ADR-0007).
"""

from __future__ import annotations

import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers

from api.base import PersonaOSView, ok
from api.errors import ApiError
from api.idempotency import idempotent
from api.views.personas import _get_persona
from api.views.policy import PROPOSERS
from apps.channels.models import ChannelAccount
from apps.content import service
from apps.content.models import ContentItem
from common import enums as E


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def item_out(i: ContentItem) -> dict:
    return {
        "content_id": str(i.id), "persona_id": i.persona.public_id,
        "run_id": i.run.public_id if i.run_id else None, "format": i.format,
        "title": i.title, "body": i.body, "language": i.language, "status": i.status,
        "status_reason": i.status_reason or None, "provenance": i.provenance,
        "disclosure_included": i.disclosure_included, "content_hash": i.content_hash,
        "version": i.version, "citations": i.citations, "scheduled_for": _iso(i.scheduled_for),
        "created_at": _iso(i.created_at),
        "publications": [{
            "channel_account_id": str(p.channel_account_id),
            "channel_type": p.channel_account.channel_type,
            "action_id": p.action.public_id if p.action_id else None,
            "status": p.status, "provider_post_id": p.provider_post_id,
            "dry_run": (p.provider_payload or {}).get("dry_run"),
            "published_at": _iso(p.published_at), "error_code": p.error_code or None,
        } for p in i.publications.select_related("channel_account", "action")],
    }


def _err(e: service.ContentError) -> ApiError:
    code = E.ErrorCode(e.code) if e.code in E.ErrorCode.values() else \
        E.ErrorCode.VALIDATION_ERROR
    return ApiError(code, str(e))


def _item(content_id: str) -> ContentItem:
    try:
        uuid.UUID(content_id)
    except ValueError:
        raise ApiError(E.ErrorCode.NOT_FOUND, "Sadržaj ne postoji.") from None
    item = ContentItem.objects.select_related("persona", "run").filter(id=content_id).first()
    if item is None:
        raise ApiError(E.ErrorCode.NOT_FOUND, "Sadržaj ne postoji.")
    return item


class DraftIn(serializers.Serializer):
    persona_id = serializers.CharField()
    topic = serializers.CharField(max_length=220, required=False, allow_blank=True, default="")
    angle = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    body = serializers.CharField(max_length=5000, required=False, allow_null=True, default=None)
    format = serializers.ChoiceField(choices=E.ContentFormat.values(),
                                     default=E.ContentFormat.POST.value)


class ContentItemsView(PersonaOSView):
    required_roles = {"POST": PROPOSERS}

    @extend_schema(operation_id="content_items_list",
                   parameters=[OpenApiParameter("persona_id", str),
                               OpenApiParameter("status", str, enum=E.ContentStatus.values())],
                   responses={200: dict})
    def get(self, request):
        qs = ContentItem.objects.select_related("persona", "run").order_by("-created_at")
        if request.query_params.get("persona_id"):
            qs = qs.filter(persona__public_id=request.query_params["persona_id"])
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        return ok([item_out(i) for i in qs[:100]])

    @extend_schema(operation_id="content_items_create", request=DraftIn, responses={201: dict})
    @idempotent
    def post(self, request):
        data = DraftIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        persona = _get_persona(v["persona_id"])
        try:
            item = service.draft(persona, topic=v["topic"], angle=v["angle"], body=v["body"],
                                 fmt=E.ContentFormat(v["format"]))
        except service.ContentError as e:
            raise _err(e) from e
        return ok(item_out(item), status=201)


class ContentItemDetailView(PersonaOSView):
    @extend_schema(operation_id="content_items_retrieve", responses={200: dict})
    def get(self, request, content_id: str):
        return ok(item_out(_item(content_id)))


class ScheduleIn(serializers.Serializer):
    channel_account_id = serializers.UUIDField()
    scheduled_for = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ContentScheduleView(PersonaOSView):
    required_roles = {"POST": PROPOSERS}

    @extend_schema(operation_id="content_items_schedule", request=ScheduleIn,
                   responses={201: dict})
    @idempotent
    def post(self, request, content_id: str):
        item = _item(content_id)
        data = ScheduleIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        acc = ChannelAccount.objects.filter(id=v["channel_account_id"]).first()
        if acc is None:
            raise ApiError(E.ErrorCode.NOT_FOUND, "Nalog ne postoji.")
        try:
            pr = service.submit(item, acc, scheduled_for=v["scheduled_for"])
        except service.ContentError as e:
            raise _err(e) from e
        item.refresh_from_db()
        return ok({"content": item_out(item), "action_id": pr.action.public_id,
                   "action_status": pr.action.status,
                   "approval_id": pr.approval.public_id if pr.approval else None},
                  status=201)
