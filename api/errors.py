"""Jedan oblik greške za ceo API. Canon §8.5.

Svaka greška — naša, DRF-ova ili Django-ova — izlazi kao:

    {"error": {"code": "...", "message": "...", "details": {...}, "retryable": false},
     "meta":  {"request_id": "...", "trace_id": "..."}}

`code` je uvek jedna od deset vrednosti `ErrorCode`, a HTTP status dolazi iz
`ERROR_HTTP_STATUS`. Klijent nikada ne mora da parsira tekst poruke da bi
znao šta se desilo.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.response import Response

from api.context import current
from common import enums as E

log = logging.getLogger("persona.api")

#: Greške koje ima smisla ponoviti bez izmene zahteva.
_RETRYABLE: frozenset[E.ErrorCode] = frozenset(
    {E.ErrorCode.RATE_LIMITED, E.ErrorCode.PROVIDER_UNAVAILABLE, E.ErrorCode.INTERNAL_ERROR}
)


class ApiError(Exception):
    """Greška sa kanonskim kodom. Status se ne zadaje — izvodi se iz koda."""

    def __init__(
        self,
        code: E.ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = E.ErrorCode(code)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}

    @property
    def status(self) -> int:
        return E.ERROR_HTTP_STATUS[self.code]


def meta() -> dict[str, str]:
    ctx = current()
    return {"request_id": ctx.request_id, "trace_id": ctx.trace_id}


def error_body(code: E.ErrorCode, message: str, details: dict | None = None) -> dict:
    return {
        "error": {
            "code": code.value,
            "message": message,
            "details": details or {},
            "retryable": code in _RETRYABLE,
        },
        "meta": meta(),
    }


def error_response(err: ApiError) -> Response:
    return Response(
        error_body(err.code, err.message, err.details), status=err.status, headers=err.headers
    )


def _from_drf(exc: drf.APIException) -> ApiError:
    if isinstance(exc, (drf.NotAuthenticated, drf.AuthenticationFailed)):
        return ApiError(E.ErrorCode.UNAUTHENTICATED, "Prijava je obavezna.")
    if isinstance(exc, drf.PermissionDenied):
        return ApiError(E.ErrorCode.FORBIDDEN, str(exc.detail) or "Nemaš pravo na ovu radnju.")
    if isinstance(exc, drf.NotFound):
        return ApiError(E.ErrorCode.NOT_FOUND, "Resurs ne postoji.")
    if isinstance(exc, drf.Throttled):
        return ApiError(E.ErrorCode.RATE_LIMITED, "Previše zahteva.")
    if isinstance(exc, drf.ValidationError):
        detail = exc.detail if isinstance(exc.detail, dict) else {"non_field_errors": exc.detail}
        return ApiError(E.ErrorCode.VALIDATION_ERROR, "Zahtev nije ispravan.", {"fields": detail})
    if isinstance(exc, (drf.ParseError, drf.UnsupportedMediaType, drf.MethodNotAllowed)):
        return ApiError(E.ErrorCode.VALIDATION_ERROR, str(exc.detail))
    return ApiError(E.ErrorCode.INTERNAL_ERROR, "Neočekivana greška.")


def exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF `EXCEPTION_HANDLER`. Sve prevodi u kanonski oblik."""
    if isinstance(exc, ApiError):
        return error_response(exc)
    if isinstance(exc, Http404):
        return error_response(ApiError(E.ErrorCode.NOT_FOUND, "Resurs ne postoji."))
    if isinstance(exc, PermissionDenied):
        return error_response(ApiError(E.ErrorCode.FORBIDDEN, "Nemaš pravo na ovu radnju."))
    if isinstance(exc, drf.APIException):
        return error_response(_from_drf(exc))
    # Nepoznata greška: loguje se sa trace_id-jem, a klijent dobija samo kod.
    # Detalj izuzetka ne ide u odgovor — može da sadrži podatke iz baze.
    log.exception("neobrađena greška trace_id=%s", current().trace_id)
    return error_response(ApiError(E.ErrorCode.INTERNAL_ERROR, "Neočekivana greška."))
