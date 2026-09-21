"""Čitanje ciklusa i akcija. Canon §8.2.

    GET /api/v1/runs/{run_id}
    GET /api/v1/actions/{action_id}
    GET /api/v1/actions/{action_id}/policy-trace

Samo čitanje. `POST /actions/propose` dolazi u F5 — predlog akcije bez
policy engine-a iza sebe bio bi upravo ono što Canon §6.2 zabranjuje.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema

from api.base import PersonaOSView, ok
from api.errors import ApiError
from api.serializers import action_out, approval_out, attempt_out, decision_out, run_out
from apps.orchestration.models import Action, AgentRun
from common import enums as E
from common import ids as I


def _lookup(model, kind: str, public_id: str, label: str):
    try:
        I.validate_public_id(kind, public_id)
    except ValueError:
        raise ApiError(E.ErrorCode.NOT_FOUND, f"{label} ne postoji.") from None
    obj = model.objects.select_related("persona").filter(public_id=public_id).first()
    if obj is None:
        raise ApiError(E.ErrorCode.NOT_FOUND, f"{label} ne postoji.")
    return obj


class RunDetailView(PersonaOSView):
    @extend_schema(operation_id="runs_retrieve", responses={200: dict})
    def get(self, request, run_id: str):
        return ok(run_out(_lookup(AgentRun, I.EntityKind.AGENT_RUN, run_id, "Run")))


class ActionDetailView(PersonaOSView):
    @extend_schema(operation_id="actions_retrieve", responses={200: dict})
    def get(self, request, action_id: str):
        return ok(action_out(_lookup(Action, I.EntityKind.ACTION, action_id, "Akcija")))


class ActionPolicyTraceView(PersonaOSView):
    """Ceo lanac jedne akcije: odluke, odobrenja, pokušaji — Canon §16.5."""

    @extend_schema(operation_id="actions_policy_trace", responses={200: dict})
    def get(self, request, action_id: str):
        a = _lookup(Action, I.EntityKind.ACTION, action_id, "Akcija")
        return ok(
            {
                "action_id": a.public_id,
                "status": a.status,
                "effective_decision_id": a.policy_decision.public_id if a.policy_decision else None,
                "decisions": [decision_out(d) for d in a.decisions.order_by("evaluated_at")],
                "approvals": [approval_out(x) for x in a.approvals.order_by("created_at")],
                "attempts": [attempt_out(t) for t in a.attempts.order_by("attempt_number")],
            }
        )
