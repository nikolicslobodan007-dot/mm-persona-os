"""Isolated, read-only Mission Control bridge (Virtual Office V1.2 LOCKED).

No business data mutation, no ORM model changes, no exposure of JSON payloads,
Django internal IDs, private dossiers or prompt fields. Human authentication
is the same session+TOTP+roles as console/auth.py.
"""

from __future__ import annotations

import functools
import secrets
from collections import Counter
from datetime import UTC

from django.core.cache import cache
from django.db.models import Count, Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from api.errors import error_body
from apps.observability.models import AuditEvent
from apps.orchestration.models import AgentPlan, PlanStep
from apps.personas.models import Assignment, Biography, Persona
from apps.policy.models import ApprovalRequest
from apps.visuals.models import VisualProfile
from common import enums as E
from console.auth import SESSION_OTP, is_operator, secure

PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
CURSOR_TTL = 30 * 60
# Positive allowlist, not a generic dump of the audit table.
EVENT_KEYS = frozenset({"plan.delegated", "plan.paused", "plan.resumed"})
IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})


def _reply(data, *, status=200):
    response = JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})
    return secure(response)


def _error(code: E.ErrorCode, message: str):
    return _reply(error_body(code, message), status=E.ERROR_HTTP_STATUS[code])


def office_json_view(fn):
    """Return JSON 401/403, unlike HTML console_view's 302 login redirect."""

    @functools.wraps(fn)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.session.get(SESSION_OTP):
            return _error(E.ErrorCode.UNAUTHENTICATED, "Prijava i TOTP su obavezni.")
        if not is_operator(request.user):
            return _error(E.ErrorCode.FORBIDDEN, "Nemaš ulogu za ovu stranu.")
        if request.method != "GET":
            return _error(E.ErrorCode.VALIDATION_ERROR, "Dozvoljen je samo GET.")
        try:
            response = fn(request, *args, **kwargs)
        except ValueError:
            return _error(E.ErrorCode.VALIDATION_ERROR, "Parametar nije ispravan.")
        return secure(response)

    return wrapped


def _utc(dt):
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _positive_limit(request):
    raw = request.GET.get("limit")
    try:
        number = PAGE_SIZE if raw in (None, "") else int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid limit") from exc
    if not 1 <= number <= MAX_PAGE_SIZE:
        raise ValueError("Invalid limit")
    return number


def _context(request, resource, filters, limit):
    return {
        "user_id": request.user.pk,
        "session_id": request.session.session_key,
        "resource": resource,
        "filters": filters,
        "limit": limit,
    }


def _page_state(request, resource, filters, limit):
    token = request.GET.get("cursor")
    if not token:
        return None
    if len(token) > 192:
        raise ValueError("Invalid cursor")
    saved = cache.get(f"office:v1:cursor:{token}")
    if not isinstance(saved, dict) or saved.get("context") != _context(
        request, resource, filters, limit
    ):
        raise ValueError("Cursor invalid, expired or bound to another session")
    return saved


def _next_cursor(request, resource, filters, limit, *, last_key, ceiling=None):
    token = secrets.token_urlsafe(32)
    data = {
        "context": _context(request, resource, filters, limit),
        "last_key": last_key,
        "ceiling": ceiling,
    }
    cache.set(f"office:v1:cursor:{token}", data, timeout=CURSOR_TTL)
    return token


def _image_profile(personas):
    """One query for all reference portraits; never return storage paths."""
    ids = [p.pk for p in personas]
    refs = VisualProfile.objects.filter(persona_id__in=ids).select_related("reference_asset")
    result = {}
    for ref in refs:
        asset = ref.reference_asset
        if (
            asset is not None
            and asset.persona_id == ref.persona_id
            and asset.kind == E.AssetKind.FACE_REFERENCE.value
            and asset.mime_type in IMAGE_MIMES
        ):
            result[ref.persona_id] = True
    return result


def _primary_assignments(personas):
    """Query current *primary* assignments, without exposing internals."""
    ids = [p.pk for p in personas]
    items = (
        Assignment.objects.filter(persona_id__in=ids, ended_at__isnull=True, is_primary=True)
        .select_related("position", "position__department", "position__department__head")
        .order_by("persona_id", "-started_at")
    )
    # Database already enforces at most one primary open assignment.
    return {a.persona_id: a for a in items}


def _list_item(persona, assignment, has_portrait):
    position = assignment.position if assignment else None
    department = position.department if position else None
    return {
        "public_id": persona.public_id,
        "display_name": persona.display_name,
        "persona_type": persona.persona_type,
        "status": persona.status,
        "runtime_environment": persona.runtime_environment,
        "trust_level": persona.trust_level,
        "disclosure_mode": persona.disclosure_mode,
        "primary_locale": persona.primary_locale,
        "department": (
            {"code": department.code, "name": department.name}
            if department else None
        ),
        "position": (
            {"code": position.code, "title": position.title}
            if position else None
        ),
        "portrait_url": (
            f"/console/office/portraits/{persona.public_id}" if has_portrait else None
        ),
    }


@require_GET
@office_json_view
def office_summary(request):
    statuses = Counter(dict(
        Persona.objects.values("status").annotate(n=Count("pk"))
        .values_list("status", "n")
    ))
    runtimes = Counter(dict(
        Persona.objects.values("runtime_environment").annotate(n=Count("pk"))
        .values_list("runtime_environment", "n")
    ))
    departments = {
        code: count
        for code, count in (
            Assignment.objects.filter(ended_at__isnull=True, is_primary=True)
            .values("position__department__code")
            .annotate(n=Count("persona_id", distinct=True))
            .values_list("position__department__code", "n")
        )
    }
    result = {
        "agents": {
            "total": Persona.objects.count(),
            "by_status": dict(statuses),
            "by_runtime": dict(runtimes),
            "by_department": departments,
        },
        "plans": {"active": AgentPlan.objects.filter(status=E.PlanStatus.ACTIVE.value).count()},
        "approvals": {
            "pending": ApprovalRequest.objects.filter(
                status=E.ApprovalStatus.PENDING.value
            ).count()
        },
    }
    return _reply(result)


@require_GET
@office_json_view
def office_agents(request):
    limit = _positive_limit(request)
    department = request.GET.get("department", "").strip()
    if len(department) > 32:
        raise ValueError("Invalid department")
    filters = {"department": department}
    state = _page_state(request, "agents", filters, limit)
    qs = Persona.objects.all().order_by("public_id")
    if department:
        qs = qs.filter(
            assignments__ended_at__isnull=True,
            assignments__is_primary=True,
            assignments__position__department__code=department,
        )
    if state is not None:
        qs = qs.filter(public_id__gt=state["last_key"])
    batch = list(qs[: limit + 1])
    more = len(batch) > limit
    batch = batch[:limit]
    assignments = _primary_assignments(batch)
    portraits = _image_profile(batch)
    next_cursor = (
        _next_cursor(request, "agents", filters, limit, last_key=batch[-1].public_id)
        if more and batch
        else None
    )
    return _reply({
        "items": [_list_item(p, assignments.get(p.pk), portraits.get(p.pk, False)) for p in batch],
        "next_cursor": next_cursor,
    })


@require_GET
@office_json_view
def office_agent(request, public_id):
    if not public_id.startswith("P-") or not public_id[2:].isdigit():
        return _error(E.ErrorCode.NOT_FOUND, "Agent ne postoji.")
    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        return _error(E.ErrorCode.NOT_FOUND, "Agent ne postoji.")
    a = _primary_assignments([p]).get(p.pk)
    v = _image_profile([p])
    result = _list_item(p, a, v.get(p.pk, False))
    dep = a.position.department if a else None
    pos = a.position if a else None
    result["department"] = (
        {"code": dep.code, "name": dep.name,
         "head_public_id": dep.head.public_id if dep.head_id else None}
        if dep else None
    )
    result["position"] = (
        {"code": pos.code, "title": pos.title, "specialty": pos.specialty,
         "level": pos.level}
        if pos else None
    )
    bio = Biography.objects.filter(persona=p).only("occupation_title", "industry").first()
    result.update({
        "disclosure_required": p.disclosure_required,
        "timezone": p.timezone,
        "activated_at": _utc(p.activated_at),
        "occupation": (
            {"title": bio.occupation_title, "industry": bio.industry}
            if bio else None
        ),
        "active_plan": None,
        "active_step": None,
    })
    plan = (
        AgentPlan.objects.filter(persona=p, status=E.PlanStatus.ACTIVE.value)
        .order_by("-priority", "-created_at").first()
    )
    if plan:
        result["active_plan"] = {
            "public_id": plan.public_id, "status": plan.status,
            "priority": plan.priority, "goal_excerpt": None,
        }
        step = (
            PlanStep.objects.filter(plan=plan, status=E.StepStatus.RUNNING.value)
            .order_by("sequence").first()
        )
        if step:
            result["active_step"] = {
                "sequence": step.sequence, "step_type": step.step_type, "status": step.status,
            }
    return _reply(result)


@require_GET
@office_json_view
def office_events(request):
    limit = _positive_limit(request)
    persona = request.GET.get("persona", "").strip()
    if persona and (not persona.startswith("P-") or not persona[2:].isdigit()):
        raise ValueError("Invalid persona")
    filters = {"persona": persona}
    state = _page_state(request, "events", filters, limit)
    qs = AuditEvent.objects.filter(event_key__in=EVENT_KEYS).select_related("persona")
    if persona:
        qs = qs.filter(persona__public_id=persona)
    ceiling = state["ceiling"] if state else qs.aggregate(v=Max("id"))["v"]
    if ceiling is not None:
        qs = qs.filter(id__lte=ceiling)
    if state:
        qs = qs.filter(id__lt=state["last_key"])
    batch = list(qs.order_by("-id")[: limit + 1])
    more = len(batch) > limit
    batch = batch[:limit]
    next_cursor = (
        _next_cursor(request, "events", filters, limit,
                     last_key=batch[-1].id, ceiling=ceiling)
        if more and batch
        else None
    )
    return _reply({
        "items": [{
            "occurred_at": _utc(e.occurred_at),
            "severity": e.severity,
            "event_key": e.event_key,
            "persona_public_id": e.persona.public_id if e.persona_id else None,
            "actor_role": e.actor_role,
        } for e in batch],
        "next_cursor": next_cursor,
    })


@require_GET
@office_json_view
def office_portrait(request, public_id):
    from apps.visuals import storage

    vp = (
        VisualProfile.objects.select_related("reference_asset", "persona")
        .filter(persona__public_id=public_id).first()
    )
    asset = vp.reference_asset if vp else None
    if (
        asset is None or asset.persona_id != vp.persona_id
        or asset.kind != E.AssetKind.FACE_REFERENCE.value
        or asset.mime_type not in IMAGE_MIMES
    ):
        return _error(E.ErrorCode.NOT_FOUND, "Portret ne postoji.")
    try:
        image_bytes = storage.get(asset.storage_key)
    except storage.StorageError:
        return _error(E.ErrorCode.NOT_FOUND, "Portret ne postoji.")
    response = HttpResponse(image_bytes, content_type=asset.mime_type)
    response["X-Content-Type-Options"] = "nosniff"
    return secure(response)


@require_GET
def office_home(request):
    from console.auth import console_view

    @console_view
    def show(_request):
        return render(_request, "console/office.html")

    return show(request)
