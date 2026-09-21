"""Cursor paginacija. Canon §8.5: `limit` podrazumevano 50, najviše 200.

Cursor a ne offset: audit i eventi rastu dok ih neko čita, pa bi offset
preskakao ili ponavljao redove. Cursor je neproziran za klijenta — sadrži
poslednji viđeni ključ sortiranja, base64 kodiran.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from django.db.models import QuerySet

from api.errors import ApiError
from common import enums as E

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _encode(value: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _decode(cursor: str) -> Any:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception as exc:  # noqa: BLE001
        raise ApiError(E.ErrorCode.VALIDATION_ERROR, "Neispravan cursor.") from exc


def parse_limit(raw: str | None) -> int:
    if raw in (None, ""):
        return DEFAULT_LIMIT
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ApiError(E.ErrorCode.VALIDATION_ERROR, "limit mora biti ceo broj.") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise ApiError(
            E.ErrorCode.VALIDATION_ERROR, f"limit mora biti između 1 i {MAX_LIMIT}."
        )
    return limit


def paginate_desc(qs: QuerySet, request, *, key: str = "id") -> tuple[list, dict]:
    """Stranica po opadajućem `key`. Vraća (redovi, meta sa `next_cursor`)."""
    limit = parse_limit(request.query_params.get("limit"))
    cursor = request.query_params.get("cursor")
    qs = qs.order_by(f"-{key}")
    if cursor:
        qs = qs.filter(**{f"{key}__lt": _decode(cursor)})
    rows = list(qs[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode(getattr(rows[-1], key)) if has_more and rows else None
    return rows, {"limit": limit, "next_cursor": next_cursor}
