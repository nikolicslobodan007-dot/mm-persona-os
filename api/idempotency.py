"""`Idempotency-Key` za svaki POST sa efektom. Canon §6.3, §8.5, §16.5.

Tok, u jednoj transakciji sa samom izmenom:

  1. Pokušaj da upišeš zapis `(scope, key)` sa hash-om zahteva.
  2. Ako drugi zahtev sa istim ključem već radi, baza drži ovaj upis dok
     prvi ne završi — jedinstveni indeks je brava. Kad prvi commit-uje,
     ovaj dobija IntegrityError, čita gotov odgovor i vraća ga.
  3. Isti ključ, drugačiji sadržaj → 409 IDEMPOTENCY_CONFLICT.
  4. Uspešan odgovor se pamti i vraća pri svakom ponavljanju, sa header-om
     `Idempotent-Replayed: true`. Greška (validacija, 5xx) poništava i sam
     zapis, pa ponovljen zahtev ide ispočetka — bezbedno, jer greška ne
     ostavlja efekat.

Rezultat: sto paralelnih istih zahteva daje jedan efekat (test iz ugovora
API v0.1 §24), bez ijedne Redis brave.
"""

from __future__ import annotations

import functools
import re
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response

from api.audit import sha256_of
from api.context import current
from api.errors import ApiError
from common import enums as E

#: Canon §6.3 — ključ živi najmanje 24 sata.
IDEMPOTENCY_TTL = timedelta(hours=24)
_REPLAYED_HEADERS = ("ETag", "Location")
_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def idempotent(view_method):
    """Dekorator za `post()` metod view-a."""

    @functools.wraps(view_method)
    def wrapper(self, request, *args, **kwargs):
        from apps.observability.models import IdempotencyRecord

        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            raise ApiError(
                E.ErrorCode.VALIDATION_ERROR,
                "Idempotency-Key je obavezan za ovu radnju (Canon §8.5).",
                {"headers": {"Idempotency-Key": "obavezan"}},
            )
        if not _KEY.match(key):
            raise ApiError(
                E.ErrorCode.VALIDATION_ERROR,
                "Idempotency-Key: 8–128 znakova, slova, cifre, . _ : -",
            )

        ctx = current()
        scope = ctx.principal or ctx.actor_id
        request_hash = sha256_of(
            {"method": request.method, "path": request.path, "body": request.data}
        )

        with transaction.atomic():
            try:
                with transaction.atomic():
                    record = IdempotencyRecord.objects.create(
                        scope=scope,
                        key=key,
                        request_hash=request_hash,
                        method=request.method,
                        path=request.path[:500],
                        expires_at=timezone.now() + IDEMPOTENCY_TTL,
                    )
            except IntegrityError:
                existing = IdempotencyRecord.objects.get(scope=scope, key=key)
                if existing.request_hash != request_hash:
                    raise ApiError(
                        E.ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Isti Idempotency-Key je već iskorišćen za drugačiji zahtev.",
                        {"key": key},
                    ) from None
                stored = existing.response_body or {}
                return Response(
                    stored.get("body"),
                    status=existing.status_code,
                    headers=stored.get("headers", {}) | {"Idempotent-Replayed": "true"},
                )

            response = view_method(self, request, *args, **kwargs)

            if response.status_code >= 500:
                transaction.set_rollback(True)
                return response
            record.status_code = response.status_code
            # ETag i Location su deo odgovora: ponovljen POST mora da vrati
            # isto što i prvi, inače klijent ne zna verziju za sledeći PATCH.
            record.response_body = {
                "body": response.data,
                "headers": {h: response[h] for h in _REPLAYED_HEADERS if h in response},
            }
            record.save(update_fields=["status_code", "response_body"])
            return response

    return wrapper
