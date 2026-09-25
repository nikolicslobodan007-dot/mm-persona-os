"""Osnova za sve view-ove: odgovor, principal, uloge. Canon §8, §15.1.

Uloge su Django grupe sa imenima iz `Role` (Canon §15.1). Nema zasebnog
IAM servera: sistem koriste Slobodan i ljudi iz firme, i šest uloga kao
grupe pokrivaju to bez ijedne dodatne komponente. Keycloak/OIDC ostaje
opcija ako zatreba SSO — zamenjuje se sloj prijave, ne ovaj kod (ADR-0004).

Servisni nalozi su korisnici čije ime počinje sa `svc_`. Oni smeju da
deklarišu tuđeg pokretača u `X-Actor-ID` (npr. planner radi u ime persone);
čovek sme da deklariše samo sebe.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from api import context as C
from api.errors import ApiError, meta
from common import enums as E

SERVICE_PREFIX = "svc_"

#: ADR-0039 — grupa poslušnika. Nije Canon uloga (§15.1 ih ima šest i ostaje
#: šest) nego **sistemski nalog** sa jednim poslom. Nalog u ovoj grupi ne
#: prolazi nigde osim na pogledima koji izričito nose `allow_runner = True`:
#: podrazumevano je zatvoreno, jer token na mašini koja vrti tuđi kod ne sme
#: da otvara ništa drugo.
RUNNER_GROUP = "runner"

#: Uloge koje smeju da čitaju audit. `viewer` ne sme — audit nosi
#: identitete ljudi i sadržaj odluka, a viewer je uloga za prikaz stanja.
AUDIT_READERS: frozenset[E.Role] = frozenset(set(E.Role) - {E.Role.VIEWER})

#: Canon §15.1 — ko upravlja personama.
PERSONA_WRITERS: frozenset[E.Role] = frozenset({E.Role.PERSONA_MANAGER, E.Role.SYSTEM_ADMIN})


def principal_of(user) -> str:
    if user is None or not user.is_authenticated:
        return ""
    name = user.get_username()
    if name.startswith(SERVICE_PREFIX):
        return f"service:{name[len(SERVICE_PREFIX):]}"
    return f"user:{name}"


def is_runner(user) -> bool:
    """Da li je pozivalac poslušnik (ADR-0039 §1)."""
    if user is None or not user.is_authenticated:
        return False
    return RUNNER_GROUP in set(user.groups.values_list("name", flat=True))


def roles_of(user) -> set[E.Role]:
    if user is None or not user.is_authenticated:
        return set()
    names = set(user.groups.values_list("name", flat=True))
    return {r for r in E.Role if r.value in names}


def ok(data: Any, *, status: int = 200, headers: dict[str, str] | None = None,
       extra_meta: dict[str, Any] | None = None) -> Response:
    """Canon oblik uspešnog odgovora: `{"data": ..., "meta": {...}}`."""
    m = meta() | {"schema_version": "1.0"} | (extra_meta or {})
    return Response({"data": data, "meta": m}, status=status, headers=headers)


class HasAnyRole(BasePermission):
    """Dozvola iz `view.required_roles[metod]`; bez unosa dovoljna je prijava."""

    message = "Nemaš ulogu potrebnu za ovu radnju."

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        # Poslušnik je zatvoren svuda osim tamo gde je izričito pušten. Ovo stoji
        # PRE provere uloga: i kad bi neko nalogu dodao ulogu, poslušnik i dalje
        # ne bi mogao nigde drugde (ADR-0039 §2).
        if is_runner(request.user) and not getattr(view, "allow_runner", False):
            return False
        needed: Iterable[E.Role] | None = getattr(view, "required_roles", {}).get(
            request.method
        )
        if not needed:
            return True
        return bool(roles_of(request.user) & set(needed))


class PersonaOSView(APIView):
    """Posle prijave upisuje principala u kontekst i proverava `X-Actor-ID`."""

    permission_classes = [HasAnyRole]
    required_roles: dict[str, frozenset[E.Role]] = {}
    #: ADR-0039 §2 — samo pogledi koji ovo nose vide poslušnika.
    allow_runner: bool = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        ctx = C.current()
        principal = principal_of(request.user)
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and principal.startswith("user:")
            and ctx.actor_id != principal
        ):
            raise ApiError(
                E.ErrorCode.FORBIDDEN,
                "Čovek može da deklariše samo sebe kao pokretača.",
                {"X-Actor-ID": ctx.actor_id, "principal": principal},
            )
        actor = ctx.actor_id
        if "actor_id" in ctx.generated:
            actor = principal or actor
        self._ctx_token = C.set_context(
            dataclasses.replace(ctx, principal=principal, actor_id=actor)
        )

    def finalize_response(self, request, response, *args, **kwargs):
        token = getattr(self, "_ctx_token", None)
        if token is not None:
            C.reset_context(token)
            self._ctx_token = None
        return super().finalize_response(request, response, *args, **kwargs)
