"""Kontekst jednog zahteva: ko, koji trag, koji zahtev. Canon §2.3, §8.5.

Čuva se u `contextvars`, ne na `request` objektu, da bi ga videli i slojevi
koji request nemaju — audit, event bus, Celery task pokrenut iz view-a.
Van HTTP zahteva (management komanda, worker) kontekst se postavlja ručno
kroz `bind()`.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

#: W3C Trace Context: `00-<32 hex trace>-<16 hex span>-<2 hex flags>`.
_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")

#: Canon §8.5 — `X-Actor-ID` kaže ko je pokrenuo radnju. Tri vrste principala.
ACTOR_PREFIXES: tuple[str, ...] = ("user:", "service:", "persona:")


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    trace_id: str
    actor_id: str
    principal: str = ""
    generated: tuple[str, ...] = ()


_current: ContextVar[RequestContext | None] = ContextVar("persona_os_request", default=None)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def trace_id_from_traceparent(value: str | None) -> str | None:
    """Vraća 32-heksadecimalni trace_id ili None ako header nije ispravan."""
    if not value:
        return None
    m = _TRACEPARENT.match(value.strip().lower())
    if not m or m.group(1) == "0" * 32:
        return None
    return m.group(1)


def current() -> RequestContext:
    """Trenutni kontekst. Van zahteva vraća sistemski, sa novim trace_id-jem."""
    ctx = _current.get()
    if ctx is None:
        return RequestContext(
            request_id=f"req_{uuid.uuid4().hex}",
            trace_id=new_trace_id(),
            actor_id="service:system",
            principal="service:system",
            generated=("request_id", "trace_id", "actor_id"),
        )
    return ctx


def set_context(ctx: RequestContext):
    return _current.set(ctx)


def reset_context(token) -> None:
    _current.reset(token)


@contextmanager
def bind(*, actor_id: str, trace_id: str | None = None, request_id: str | None = None):
    """Kontekst za kod koji ne dolazi kroz HTTP — komande, workeri, testovi."""
    ctx = RequestContext(
        request_id=request_id or f"req_{uuid.uuid4().hex}",
        trace_id=trace_id or new_trace_id(),
        actor_id=actor_id,
        principal=actor_id,
    )
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)
