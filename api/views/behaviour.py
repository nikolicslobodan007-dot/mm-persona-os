"""Behaviour endpoint-i. Canon §8.2.

    POST /api/v1/personas/{public_id}/wake              → 202 + run_id
    POST /api/v1/personas/{public_id}/behaviour/tick    → 200 + odluka
    GET  /api/v1/ops/personas/{public_id}/timeline      → buđenja, i ona bez akcije

`wake` je operatorski zadatak (§11.2, prioritet 100): preskače kockicu
rutine, ali ne i budžet, energiju ni cooldown. `tick` je isto buđenje koje
bi napravio scheduler — korisno za proveru rutine bez čekanja prozora.

U F3 buđenje traje milisekunde (nema LLM-a), pa se izvršava odmah i odgovor
već nosi `run_id`. Kad planer dobije LLM, `wake` postaje asinhron sa run-om
u stanju RUNNING — ugovor (202 + run_id) ostaje isti (ADR-0005).
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema

from api.base import PersonaOSView, ok
from api.errors import ApiError
from api.idempotency import idempotent
from api.pagination import paginate_desc
from api.serializers import run_brief, run_out
from api.views.personas import _get_persona
from apps.behaviour import service
from apps.orchestration.models import AgentRun
from common import enums as E

#: Ko sme da budi personu ručno. Canon §15.1 — operator vodi dnevni rad.
WAKERS: frozenset[E.Role] = frozenset(
    {E.Role.OPERATOR, E.Role.PERSONA_MANAGER, E.Role.SYSTEM_ADMIN}
)


def _wake(public_id: str, reason: E.WakePriority):
    p = _get_persona(public_id)
    if E.PersonaStatus(p.status) not in E.WAKEABLE_BY_OPERATOR:
        raise ApiError(
            E.ErrorCode.VALIDATION_ERROR,
            f"Persona u statusu {p.status} se ne budi.",
            {"status": p.status, "allowed": sorted(s.value for s in E.WAKEABLE_BY_OPERATOR)},
        )
    return service.wake(p, reason)


class PersonaWakeView(PersonaOSView):
    required_roles = {"POST": WAKERS}

    @extend_schema(operation_id="personas_wake", request=None, responses={202: dict})
    @idempotent
    def post(self, request, public_id: str):
        run = _wake(public_id, E.WakePriority.OPERATOR_TASK)
        return ok({"run_id": run.public_id, "decision": run.decision,
                   "reason_code": run.reason_code}, status=202,
                  headers={"Location": f"/api/v1/runs/{run.public_id}"})


class BehaviourTickView(PersonaOSView):
    required_roles = {"POST": WAKERS}

    @extend_schema(operation_id="personas_behaviour_tick", request=None, responses={200: dict})
    @idempotent
    def post(self, request, public_id: str):
        run = _wake(public_id, E.WakePriority.ROUTINE_WINDOW)
        return ok(run_out(run))


class PersonaTimelineView(PersonaOSView):
    @extend_schema(
        operation_id="ops_persona_timeline",
        parameters=[
            OpenApiParameter("decision", str, enum=E.WakeDecision.values()),
            OpenApiParameter("limit", int),
            OpenApiParameter("cursor", str),
        ],
        responses={200: dict},
    )
    def get(self, request, public_id: str):
        p = _get_persona(public_id)
        qs = AgentRun.objects.filter(persona=p)
        decision = request.query_params.get("decision")
        if decision:
            if decision not in E.WakeDecision.values():
                raise ApiError(E.ErrorCode.VALIDATION_ERROR,
                               f"decision: nepoznata vrednost {decision!r}.",
                               {"allowed": E.WakeDecision.values()})
            qs = qs.filter(decision=decision)
        rows, page = paginate_desc(qs, request, key="public_id")
        return ok([run_brief(r) for r in rows], extra_meta={"page": page})
