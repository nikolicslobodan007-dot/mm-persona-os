"""Persona endpoint-i. Canon §8.2.

    GET    /api/v1/personas
    POST   /api/v1/personas                      Idempotency-Key obavezan
    GET    /api/v1/personas/{public_id}          vraća ETag
    PATCH  /api/v1/personas/{public_id}          If-Match obavezan
    GET    /api/v1/personas/{public_id}/snapshot

Kreiranje ne emituje event: Canon §7.2 nema `persona.*` u katalogu, a
event van kataloga ne sme da postoji (§7.3). Trag kreiranja je audit red.
`wake` i `behaviour/tick` dolaze u F3, zajedno sa scheduler-om kome služe.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import F
from drf_spectacular.utils import OpenApiParameter, extend_schema

from api import audit
from api.base import PERSONA_WRITERS, PersonaOSView, ok
from api.errors import ApiError
from api.idempotency import idempotent
from api.pagination import paginate_desc
from api.serializers import (
    PersonaCreateIn,
    PersonaPatchIn,
    etag_for,
    parse_if_match,
    persona_out,
    snapshot_out,
    unique_slug,
)
from apps.personas.models import Persona
from common import enums as E
from common import ids as I

_LIST_FILTERS = {
    "status": E.PersonaStatus,
    "runtime_environment": E.RuntimeEnvironment,
    "persona_type": E.PersonaType,
}


def _get_persona(public_id: str) -> Persona:
    try:
        I.validate_public_id(I.EntityKind.PERSONA, public_id)
    except ValueError:
        raise ApiError(E.ErrorCode.NOT_FOUND, "Persona ne postoji.") from None
    p = Persona.objects.filter(public_id=public_id).first()
    if p is None:
        raise ApiError(E.ErrorCode.NOT_FOUND, "Persona ne postoji.")
    return p


def _next_public_id() -> str:
    """Sledeći slobodan P-broj. Zaključava tabelu kratko, da dva paralelna
    kreiranja ne dobiju isti broj."""
    last = (
        Persona.objects.select_for_update()
        .order_by("-public_id")
        .values_list("public_id", flat=True)
        .first()
    )
    n = I.parse_persona_number(last) + 1 if last else 1
    return I.persona_public_id(n)


class PersonaListView(PersonaOSView):
    required_roles = {"POST": PERSONA_WRITERS}

    @extend_schema(
        operation_id="personas_list",
        parameters=[
            OpenApiParameter("status", str, enum=E.PersonaStatus.values()),
            OpenApiParameter("runtime_environment", str, enum=E.RuntimeEnvironment.values()),
            OpenApiParameter("persona_type", str, enum=E.PersonaType.values()),
            OpenApiParameter("limit", int),
            OpenApiParameter("cursor", str),
        ],
        responses={200: dict},
    )
    def get(self, request):
        qs = Persona.objects.all()
        for field, enum in _LIST_FILTERS.items():
            value = request.query_params.get(field)
            if value:
                if value not in enum.values():
                    raise ApiError(
                        E.ErrorCode.VALIDATION_ERROR,
                        f"{field}: nepoznata vrednost {value!r}.",
                        {"allowed": enum.values()},
                    )
                qs = qs.filter(**{field: value})
        rows, page = paginate_desc(qs, request, key="public_id")
        return ok([persona_out(p) for p in rows], extra_meta={"page": page})

    @extend_schema(operation_id="personas_create", request=PersonaCreateIn, responses={201: dict})
    @idempotent
    def post(self, request):
        data = PersonaCreateIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data

        with transaction.atomic():
            public_id = v.get("public_id") or _next_public_id()
            if Persona.objects.filter(public_id=public_id).exists():
                raise ApiError(
                    E.ErrorCode.VALIDATION_ERROR,
                    f"{public_id} već postoji.",
                    {"fields": {"public_id": "zauzet"}},
                )
            slug = v.get("slug") or unique_slug(v["display_name"])
            if Persona.objects.filter(slug=slug).exists():
                raise ApiError(
                    E.ErrorCode.VALIDATION_ERROR,
                    f"slug {slug!r} je zauzet.",
                    {"fields": {"slug": "zauzet"}},
                )
            p = Persona.objects.create(
                public_id=public_id,
                slug=slug,
                display_name=v["display_name"],
                persona_type=v["persona_type"],
                status=E.PersonaStatus.DRAFT,
                runtime_environment=E.RuntimeEnvironment.SIMULATION,
                trust_level=E.TrustLevel.L0,
                disclosure_mode=v["disclosure_mode"],
                disclosure_required=v["disclosure_required"],
                primary_locale=v["primary_locale"],
                timezone=v["timezone"],
                metadata=v.get("metadata") or {},
            )
            out = persona_out(p)
            audit.record("api.persona.created", persona=p, after=out)
        return ok(out, status=201, headers={"ETag": etag_for(p.version),
                                            "Location": f"/api/v1/personas/{p.public_id}"})


class PersonaDetailView(PersonaOSView):
    required_roles = {"PATCH": PERSONA_WRITERS}

    @extend_schema(operation_id="personas_retrieve", responses={200: dict})
    def get(self, request, public_id: str):
        p = _get_persona(public_id)
        return ok(persona_out(p), headers={"ETag": etag_for(p.version)})

    @extend_schema(
        operation_id="personas_partial_update",
        request=PersonaPatchIn,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
        responses={200: dict},
    )
    def patch(self, request, public_id: str):
        expected = parse_if_match(request.headers.get("If-Match"))
        if expected is None:
            raise ApiError(
                E.ErrorCode.VALIDATION_ERROR,
                'If-Match je obavezan za izmenu (Canon §8.5), npr. If-Match: "v3".',
                {"headers": {"If-Match": "obavezan"}},
            )
        with transaction.atomic():
            p = _get_persona(public_id)
            data = PersonaPatchIn(data=request.data, context={"persona": p})
            data.is_valid(raise_exception=True)
            before = persona_out(p)

            # Optimistička brava: UPDATE ... WHERE version = očekivana.
            # Nula pogođenih redova znači da je neko drugi izmenio personu
            # u međuvremenu — njegova izmena ostaje, ova se odbija.
            changed = Persona.objects.filter(pk=p.pk, version=expected).update(
                **data.validated_data, version=F("version") + 1
            )
            if changed == 0:
                current_version = Persona.objects.values_list("version", flat=True).get(pk=p.pk)
                raise ApiError(
                    E.ErrorCode.VERSION_CONFLICT,
                    "Persona je u međuvremenu izmenjena.",
                    {"expected": expected, "current": current_version},
                    headers={"ETag": etag_for(current_version)},
                )
            p.refresh_from_db()
            after = persona_out(p)
            audit.record(
                "api.persona.updated",
                persona=p,
                before=before,
                after=after,
                details={"fields": sorted(data.validated_data)},
            )
        return ok(after, headers={"ETag": etag_for(p.version)})


class PersonaSnapshotView(PersonaOSView):
    @extend_schema(operation_id="personas_snapshot", responses={200: dict})
    def get(self, request, public_id: str):
        p = _get_persona(public_id)
        return ok(snapshot_out(p), headers={"ETag": etag_for(p.version)})
