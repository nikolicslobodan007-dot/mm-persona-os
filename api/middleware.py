"""Header-i zahteva: `X-Request-ID`, `traceparent`, `X-Actor-ID`. Canon §8.5.

Canon ih proglašava obaveznim. Sprovodi se ovako:

  - **Na zahtevima koji menjaju stanje** (POST, PUT, PATCH, DELETE pod
    `/api/v1/`) sva tri moraju biti poslata, inače 400 VALIDATION_ERROR.
    Radnja bez traga i bez imenovanog pokretača ne sme ni da počne.
  - **Na čitanjima** se ono što nedostaje generiše, i to se beleži u
    kontekstu (`generated`). Čitanje nema efekat, a odbijanje GET-a iz
    pregledača zbog nedostajućeg header-a ne štiti ništa.
  - **Webhook-ovi** (`/api/v1/webhooks/`) su izuzeti: šalje ih provajder, ne
    naš klijent, i on ove header-e ne poznaje. Njihova zaštita je potpis.

Odgovor uvek vraća `X-Request-ID` i `X-Trace-ID`, da bi se greška iz
klijenta mogla naći u logu jednim pretraživanjem.
"""

from __future__ import annotations

import json
import re
import uuid

from django.http import HttpResponse

from api.context import (
    ACTOR_PREFIXES,
    RequestContext,
    new_trace_id,
    reset_context,
    set_context,
    trace_id_from_traceparent,
)
from api.errors import error_body
from common import enums as E

_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_API_PREFIX = "/api/v1/"
# Javna odjava (RFC 8058) dolazi iz mejl klijenta, bez naših header-a (ADR-0008).
_EXEMPT_PREFIXES = ("/api/v1/webhooks/", "/api/v1/mail/unsubscribe")


def _reject(message: str, details: dict, ctx: RequestContext) -> HttpResponse:
    token = set_context(ctx)
    try:
        body = error_body(E.ErrorCode.VALIDATION_ERROR, message, details)
    finally:
        reset_context(token)
    resp = HttpResponse(
        json.dumps(body, ensure_ascii=False),
        status=E.ERROR_HTTP_STATUS[E.ErrorCode.VALIDATION_ERROR],
        content_type="application/json; charset=utf-8",
    )
    resp["X-Request-ID"] = ctx.request_id
    resp["X-Trace-ID"] = ctx.trace_id
    return resp


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        in_api = path.startswith(_API_PREFIX)
        exempt = path.startswith(_EXEMPT_PREFIXES)
        strict = in_api and not exempt and request.method in _UNSAFE

        raw_request_id = request.headers.get("X-Request-ID", "").strip()
        raw_trace = request.headers.get("traceparent", "").strip()
        raw_actor = request.headers.get("X-Actor-ID", "").strip()

        generated: list[str] = []
        problems: dict[str, str] = {}

        request_id = raw_request_id if _REQUEST_ID.match(raw_request_id or "") else ""
        if not request_id:
            if raw_request_id:
                problems["X-Request-ID"] = "8–128 znakova: slova, cifre, . _ : -"
            elif strict:
                problems["X-Request-ID"] = "obavezan"
            request_id = f"req_{uuid.uuid4().hex}"
            generated.append("request_id")

        trace_id = trace_id_from_traceparent(raw_trace)
        if not trace_id:
            if raw_trace:
                problems["traceparent"] = "W3C oblik: 00-<32 hex>-<16 hex>-<2 hex>"
            elif strict:
                problems["traceparent"] = "obavezan"
            trace_id = new_trace_id()
            generated.append("trace_id")

        actor_id = raw_actor
        if not actor_id.startswith(ACTOR_PREFIXES) or len(actor_id) > 180:
            if raw_actor:
                problems["X-Actor-ID"] = "mora početi sa user:, service: ili persona:"
            elif strict:
                problems["X-Actor-ID"] = "obavezan"
            actor_id = "user:anonymous"
            generated.append("actor_id")

        ctx = RequestContext(
            request_id=request_id,
            trace_id=trace_id,
            actor_id=actor_id,
            generated=tuple(generated),
        )

        # Neispravan header se odbija uvek; nedostajući samo kad radnja menja stanje.
        if in_api and not exempt and problems:
            return _reject(
                "Header-i zahteva nisu ispravni (Canon §8.5).", {"headers": problems}, ctx
            )

        request.persona_ctx = ctx
        token = set_context(ctx)
        try:
            response = self.get_response(request)
        finally:
            reset_context(token)
        response["X-Request-ID"] = ctx.request_id
        response["X-Trace-ID"] = ctx.trace_id
        return response
