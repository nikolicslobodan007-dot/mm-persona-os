"""Audit i zdravlje sistema. Canon §8.2 (`GET /api/v1/audit`), §16.5."""

from __future__ import annotations

from datetime import datetime

from django.db import connection
from django.http import JsonResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema

from api.base import AUDIT_READERS, PersonaOSView, ok
from api.errors import ApiError
from api.pagination import paginate_desc
from api.serializers import audit_out
from apps.observability.models import AuditEvent
from common import enums as E


class AuditListView(PersonaOSView):
    required_roles = {"GET": AUDIT_READERS}

    @extend_schema(
        operation_id="audit_list",
        parameters=[
            OpenApiParameter("event_key", str),
            OpenApiParameter("persona_id", str),
            OpenApiParameter("trace_id", str),
            OpenApiParameter("since", str, description="ISO-8601 UTC"),
            OpenApiParameter("limit", int),
            OpenApiParameter("cursor", str),
        ],
        responses={200: dict},
    )
    def get(self, request):
        qs = AuditEvent.objects.select_related("persona")
        q = request.query_params
        if q.get("event_key"):
            qs = qs.filter(event_key=q["event_key"])
        if q.get("persona_id"):
            qs = qs.filter(persona__public_id=q["persona_id"])
        if q.get("trace_id"):
            qs = qs.filter(trace_id=q["trace_id"])
        if q.get("since"):
            try:
                since = datetime.fromisoformat(q["since"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise ApiError(E.ErrorCode.VALIDATION_ERROR, "since nije ISO-8601.") from exc
            qs = qs.filter(occurred_at__gte=since)
        rows, page = paginate_desc(qs, request, key="id")
        return ok([audit_out(e) for e in rows], extra_meta={"page": page})


_HOME = """<!doctype html><html lang="sr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>MM Persona OS</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;
color:#1b1f24;background:#fafafa}}h1{{font-size:1.4rem;margin:0 0 .25rem}}
.s{{display:inline-block;padding:.1rem .5rem;border-radius:.3rem;background:{bg};color:#fff}}
small{{color:#666}}</style></head><body><h1>MM Persona OS</h1>
<p>Interni sistem Web Korporacije. Pristup samo uz nalog.</p>
<p>Status: <span class="s">{status}</span> <small>aplikacija ok · baza {db}</small></p>
</body></html>"""


def home(request):
    """Početna strana — samo naziv i zdravlje, bez ikakvih podataka o personama.
    Nije zaštićena prijavom, zato ne sme da otkrije ništa više od ovoga."""
    from django.http import HttpResponse

    try:
        with connection.cursor() as c:
            c.execute("select 1")
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "nedostupna"
    good = db == "ok"
    html = _HOME.format(status="radi" if good else "delimično", db=db,
                        bg="#1a7f37" if good else "#b35900")
    resp = HttpResponse(html, status=200 if good else 503)
    resp["X-Robots-Tag"] = "noindex, nofollow"
    return resp


def healthz(request):
    """Za Caddy i ručnu proveru. Van `/api/v1/` jer nije deo ugovora (Canon §8.2)."""
    try:
        with connection.cursor() as c:
            c.execute("select 1")
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "down"
    status = 200 if db == "ok" else 503
    return JsonResponse({"status": "ok" if status == 200 else "degraded", "db": db},
                        status=status)
