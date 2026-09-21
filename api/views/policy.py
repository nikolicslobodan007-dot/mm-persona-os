"""Policy, odobrenja, poverenje i kill-switch. Canon §8.2–8.4, §9, §15.

    POST /api/v1/actions/propose                      predlog → odluka (Idempotency-Key)
    POST /api/v1/policy/evaluate                      jedna evaluacija (sa action_id: nova odluka)
    POST /api/v1/policy/evaluate/batch                do 50 proba bez upisa
    GET  /api/v1/approvals                            red za odobravanje
    POST /api/v1/approvals/{id}/decision              APPROVED / APPROVED_WITH_CHANGES / REJECTED
    POST /api/v1/personas/{public_id}/trust/change    promena poverenja po capability-ju
    GET|POST /api/v1/kill-switches                    pregled / aktiviranje / puštanje
    GET  /api/v1/policy/incidents                     incidenti

Probna evaluacija (bez `action_id`) ne upisuje ništa i vraća `decision_id: null`
— korisna za „šta bi policy rekao", nikad ne vodi do izvršenja.
"""

from __future__ import annotations

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers

from api.base import AUDIT_READERS, PersonaOSView, ok, roles_of
from api.context import current
from api.errors import ApiError
from api.idempotency import idempotent
from api.pagination import paginate_desc
from api.serializers import (
    action_out,
    approval_out,
    decision_out,
    incident_out,
    kill_switch_out,
)
from api.views.personas import _get_persona
from apps.channels.models import ChannelAccount
from apps.orchestration.models import Action, AgentRun
from apps.policy import config, service
from apps.policy.models import ApprovalRequest, KillSwitch, PolicyIncident
from common import enums as E

PROPOSERS = frozenset({E.Role.OPERATOR, E.Role.PERSONA_MANAGER, E.Role.SYSTEM_ADMIN})


def _err(exc: service.PolicyError) -> ApiError:
    code = E.ErrorCode(exc.code) if exc.code in E.ErrorCode.values() else \
        E.ErrorCode.VALIDATION_ERROR
    return ApiError(code, str(exc), exc.details)


class ProposalIn(serializers.Serializer):
    persona_id = serializers.CharField()
    action_type = serializers.CharField(max_length=64)
    payload = serializers.DictField(required=False, default=dict)
    intent = serializers.CharField(max_length=2000, required=False, default="", allow_blank=True)
    target_ref = serializers.CharField(max_length=500, required=False, default="",
                                       allow_blank=True)
    channel_account_id = serializers.UUIDField(required=False, allow_null=True)
    run_id = serializers.CharField(required=False, allow_null=True)


class EvaluateIn(ProposalIn):
    persona_id = serializers.CharField(required=False)
    action_type = serializers.CharField(max_length=64, required=False)
    action_id = serializers.CharField(required=False)


class BatchIn(serializers.Serializer):
    items = serializers.ListField(child=ProposalIn(), min_length=1, max_length=50)


class DecisionIn(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["APPROVED", "APPROVED_WITH_CHANGES", "REJECTED"])
    payload_override = serializers.DictField(required=False)
    reason = serializers.CharField(max_length=2000, required=False, default="", allow_blank=True)
    decided_by = serializers.CharField(required=False)


class TrustIn(serializers.Serializer):
    capability = serializers.CharField(max_length=64)
    level = serializers.ChoiceField(choices=E.TrustLevel.values())
    reason = serializers.CharField(max_length=2000)
    evidence_ref = serializers.CharField(max_length=512, required=False, default="",
                                         allow_blank=True)


class KillSwitchIn(serializers.Serializer):
    operation = serializers.ChoiceField(choices=["activate", "clear"], default="activate")
    scope = serializers.ChoiceField(choices=E.KillSwitchScope.values(), required=False)
    target = serializers.CharField(max_length=180, required=False, default="", allow_blank=True)
    kill_switch_id = serializers.UUIDField(required=False)
    reason = serializers.CharField(max_length=2000)


def _channel(persona, channel_id):
    if not channel_id:
        return None
    ch = ChannelAccount.objects.filter(id=channel_id, persona=persona).first()
    if ch is None:
        raise ApiError(E.ErrorCode.NOT_FOUND, "Nalog kanala ne postoji za ovu personu.")
    return ch


def _run(persona, run_id):
    if not run_id:
        return None
    run = AgentRun.objects.filter(public_id=run_id, persona=persona).first()
    if run is None:
        raise ApiError(E.ErrorCode.NOT_FOUND, "Run ne postoji za ovu personu.")
    return run


def _dry(v: dict) -> dict:
    p = _get_persona(v["persona_id"])
    payload = v.get("payload") or {}
    ctx = service.build_context(p, v["action_type"], payload, intent=v.get("intent", ""),
                                channel=_channel(p, v.get("channel_account_id")),
                                now=timezone.now(), chash=service.content_hash(payload))
    r, failed, _ = service.evaluate_safely(ctx)
    return service.decision_view(r, decision_id=None, input_hash=None) | {
        "dry_run": True, "fail_closed": failed}


class ActionProposeView(PersonaOSView):
    required_roles = {"POST": PROPOSERS}

    @extend_schema(operation_id="actions_propose", request=ProposalIn, responses={201: dict})
    @idempotent
    def post(self, request):
        data = ProposalIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        p = _get_persona(v["persona_id"])
        prop = service.propose(p, v["action_type"], v["payload"], intent=v["intent"],
                               target_ref=v["target_ref"],
                               channel=_channel(p, v.get("channel_account_id")),
                               run=_run(p, v.get("run_id")))
        a = Action.objects.select_related("persona", "run", "policy_decision").get(
            pk=prop.action.pk)
        body = {"action": action_out(a),
                "decision": decision_out(prop.decision) if prop.decision else None,
                "approval": approval_out(prop.approval) if prop.approval else None,
                "created": prop.created}
        return ok(body, status=201 if prop.created else 200)


class PolicyEvaluateView(PersonaOSView):
    required_roles = {"POST": AUDIT_READERS}

    @extend_schema(operation_id="policy_evaluate", request=EvaluateIn, responses={200: dict})
    def post(self, request):
        data = EvaluateIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if v.get("action_id"):
            if not roles_of(request.user) & PROPOSERS:
                raise ApiError(E.ErrorCode.FORBIDDEN,
                               "Ponovna evaluacija postojeće akcije traži ulogu predlagača.")
            a = Action.objects.select_related("persona").filter(public_id=v["action_id"]).first()
            if a is None:
                raise ApiError(E.ErrorCode.NOT_FOUND, "Akcija ne postoji.")
            try:
                d = service.reevaluate(a)
            except service.PolicyError as exc:
                raise _err(exc) from exc
            return ok(decision_out(d) | {"dry_run": False})
        if not v.get("persona_id") or not v.get("action_type"):
            raise ApiError(E.ErrorCode.VALIDATION_ERROR,
                           "Potreban je action_id ili persona_id + action_type.")
        return ok(_dry(v))


class PolicyEvaluateBatchView(PersonaOSView):
    required_roles = {"POST": AUDIT_READERS}

    @extend_schema(operation_id="policy_evaluate_batch", request=BatchIn, responses={200: dict})
    def post(self, request):
        data = BatchIn(data=request.data)
        data.is_valid(raise_exception=True)
        return ok([_dry(item) for item in data.validated_data["items"]])


class ApprovalListView(PersonaOSView):
    required_roles = {"GET": AUDIT_READERS}

    @extend_schema(
        operation_id="approvals_list",
        parameters=[OpenApiParameter("status", str, enum=E.ApprovalStatus.values()),
                    OpenApiParameter("persona_id", str), OpenApiParameter("limit", int),
                    OpenApiParameter("cursor", str)],
        responses={200: dict},
    )
    def get(self, request):
        qs = ApprovalRequest.objects.select_related("action", "action__persona")
        q = request.query_params
        status = q.get("status", E.ApprovalStatus.PENDING.value)
        if status not in E.ApprovalStatus.values():
            raise ApiError(E.ErrorCode.VALIDATION_ERROR, f"status: nepoznata vrednost {status!r}.")
        qs = qs.filter(status=status)
        if q.get("persona_id"):
            qs = qs.filter(action__persona__public_id=q["persona_id"])
        rows, page = paginate_desc(qs, request, key="public_id")
        return ok([approval_out(a) for a in rows], extra_meta={"page": page})


class ApprovalDecisionView(PersonaOSView):
    @extend_schema(operation_id="approvals_decision", request=DecisionIn, responses={200: dict})
    @idempotent
    def post(self, request, approval_id: str):
        # Canon §15.1 — `approvals.decide` je dozvola, ne uloga.
        if not request.user.has_perm("policy.decide_approval"):
            raise ApiError(E.ErrorCode.FORBIDDEN, "Nemaš dozvolu za odlučivanje o odobrenjima.")
        ap = ApprovalRequest.objects.select_related("action", "action__persona").filter(
            public_id=approval_id).first()
        if ap is None:
            raise ApiError(E.ErrorCode.NOT_FOUND, "Odobrenje ne postoji.")
        data = DecisionIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        principal = current().principal
        if v.get("decided_by") and v["decided_by"] != principal:
            raise ApiError(E.ErrorCode.FORBIDDEN, "decided_by mora biti prijavljeni korisnik.",
                           {"decided_by": v["decided_by"], "principal": principal})
        roles = roles_of(request.user) & E.APPROVAL_DECIDERS
        role = sorted(roles, key=lambda r: r.value)[0] if roles else None
        try:
            ap = service.decide_approval(ap, E.ApprovalStatus(v["decision"]), actor=principal,
                                         role=role, reason=v["reason"],
                                         payload_override=v.get("payload_override"))
        except service.PolicyError as exc:
            raise _err(exc) from exc
        a = Action.objects.select_related("persona", "run", "policy_decision").get(
            pk=ap.action_id)
        fresh = ApprovalRequest.objects.select_related("action", "action__persona").get(pk=ap.pk)
        return ok({"approval": approval_out(fresh), "action": action_out(a),
                   "decision": decision_out(a.policy_decision) if a.policy_decision else None})


class TrustChangeView(PersonaOSView):
    required_roles = {"POST": E.TRUST_CHANGERS}

    @extend_schema(operation_id="personas_trust_change", request=TrustIn, responses={200: dict})
    @idempotent
    def post(self, request, public_id: str):
        p = _get_persona(public_id)
        data = TrustIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            changed = service.change_trust(p, v["capability"], E.TrustLevel(v["level"]),
                                           actor=current().principal, reason=v["reason"],
                                           evidence=v["evidence_ref"])
        except service.PolicyError as exc:
            raise _err(exc) from exc
        current_map = service.trust_map(p)
        matrix = {c: current_map.get(c, E.TrustLevel.L0).value
                  for c in config.capabilities()["capabilities"]}
        # Canon §3.11 — jedan broj u prikazu je MINIMUM po capability-jima.
        return ok({"persona_id": p.public_id, "changed": changed, "trust": matrix,
                   "display_level": min(matrix.values())})


class KillSwitchView(PersonaOSView):
    required_roles = {"GET": AUDIT_READERS, "POST": E.KILL_SWITCH_ACTIVATORS}

    @extend_schema(operation_id="kill_switches_list",
                   parameters=[OpenApiParameter("active", bool)], responses={200: dict})
    def get(self, request):
        qs = KillSwitch.objects.all().order_by("-activated_at")
        if request.query_params.get("active", "true").lower() != "false":
            qs = qs.filter(is_active=True)
        return ok([kill_switch_out(k) for k in qs[:200]])

    @extend_schema(operation_id="kill_switches_post", request=KillSwitchIn, responses={201: dict})
    @idempotent
    def post(self, request):
        data = KillSwitchIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        actor = current().principal
        try:
            if v["operation"] == "clear":
                if not roles_of(request.user) & E.KILL_SWITCH_RELEASERS:
                    raise ApiError(E.ErrorCode.FORBIDDEN,
                                   "Puštanje kill-switch-a traži trust_safety, runtime_admin "
                                   "ili system_admin.")
                ks = KillSwitch.objects.filter(id=v.get("kill_switch_id")).first()
                if ks is None:
                    raise ApiError(E.ErrorCode.NOT_FOUND, "Kill-switch ne postoji.")
                return ok(kill_switch_out(service.release_kill_switch(
                    ks, actor=actor, reason=v["reason"])))
            if not v.get("scope"):
                raise ApiError(E.ErrorCode.VALIDATION_ERROR, "scope je obavezan.")
            ks = service.activate_kill_switch(E.KillSwitchScope(v["scope"]), v["target"],
                                              reason=v["reason"], actor=actor)
        except service.PolicyError as exc:
            raise _err(exc) from exc
        return ok(kill_switch_out(ks), status=201)


class IncidentListView(PersonaOSView):
    required_roles = {"GET": AUDIT_READERS}

    @extend_schema(
        operation_id="policy_incidents_list",
        parameters=[OpenApiParameter("status", str, enum=E.IncidentStatus.values()),
                    OpenApiParameter("severity", str, enum=E.IncidentSeverity.values()),
                    OpenApiParameter("limit", int), OpenApiParameter("cursor", str)],
        responses={200: dict},
    )
    def get(self, request):
        qs = PolicyIncident.objects.select_related("persona", "action")
        q = request.query_params
        if q.get("status"):
            qs = qs.filter(status=q["status"])
        if q.get("severity"):
            qs = qs.filter(severity=q["severity"])
        rows, page = paginate_desc(qs, request, key="public_id")
        return ok([incident_out(i) for i in rows], extra_meta={"page": page})
