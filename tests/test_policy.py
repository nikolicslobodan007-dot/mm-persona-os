"""F5 — Policy / Approval / Trust / Kill-switch / Gateway. ADR-0007.

Invarijante iz Policy v0.1 §19.1 i Canon §6.2, §9, §15, §16.5:
  - nijedna akcija u QUEUED bez odluke ALLOW;
  - DENY i EXPIRED se nikad ne izvršavaju;
  - REQUIRE_APPROVAL ne postaje izvršiv bez odobrenja ISTOG hash-a;
  - aktivan kill-switch uvek pobeđuje raniji ALLOW;
  - izmena sadržaja traži novu evaluaciju;
  - tvrda zabrana → SEV1 + L0 + SUSPENDED.
"""

from __future__ import annotations

import io
import threading
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.context import bind
from apps.observability.models import EventOutbox
from apps.orchestration.models import Action
from apps.personas.models import Persona
from apps.policy import engine, gateway, guards, service
from apps.policy.models import (
    ApprovalRequest,
    CapabilityGrant,
    KillSwitch,
    PolicyDecision,
    PolicyIncident,
    TrustState,
)
from common import enums as E
from tests.conftest import READ_OK, UA, _propose, _read, requires_db  # noqa: F401

pytestmark = [requires_db]
# ---------------------------------------------------------------- guards


class TestGuards:
    @pytest.mark.parametrize("text, pid", [
        ("Ja sam prava osoba, verujte mi", "IDENTITY_IMPERSONATION"),
        ("I am not an AI, just a regular person", "IDENTITY_IMPERSONATION"),
        ("Objavi ovo bez AI oznake", "DISCLOSURE_CONCEALMENT"),
        ("Moj JMBG je 0101990710012", "GOVERNMENT_IDENTIFIERS"),
        ("Reši captcha pa nastavi", "PLATFORM_EVASION"),
        ("Koristi stealth browser", "PLATFORM_EVASION"),
        ("Pošaljite mi vašu lozinku za nalog", "SENSITIVE_DATA_SOLICITATION"),
    ])
    def test_text_patterns(self, text, pid):
        assert pid in guards.prohibitions("channel.post.create", {"text": text})

    def test_clean_text_passes(self):
        assert guards.prohibitions("channel.post.create",
                                   {"text": "Kratka analiza B2B nabavke, tri saveta."}) == []

    def test_flags_and_bulk(self):
        assert "REAL_PERSON_LIKENESS" in guards.prohibitions(
            "channel.post.create", {"flags": {"media.real_person_likeness": True}})
        assert "BULK_UNSOLICITED" in guards.prohibitions("mail.send", {"recipients_count": 500})


# ---------------------------------------------------------------- engine


def _ctx(**kw):
    base = dict(persona_id="P-00001", persona_status=E.PersonaStatus.READY,
                action_type="browser.page.read", payload=_read(), now=timezone.now())
    return engine.Context(**(base | kw))


class TestEngine:
    def test_risk_is_sum_minus_credit_and_zone_is_derived(self):
        r = engine.evaluate(_ctx())
        c = r.risk_components
        assert r.risk_score == max(0, min(100, sum(v for k, v in c.items()
                                                    if k != "trust_credit") - c["trust_credit"]))
        assert r.effect == E.PolicyEffect.ALLOW and r.zone == E.Zone.GREEN

    def test_deny_beats_everything(self):
        r = engine.evaluate(_ctx(kill_switches=[("GLOBAL", "")]))
        assert r.effect == E.PolicyEffect.DENY
        assert r.reason_code == E.PolicyReason.KILL_SWITCH_ACTIVE

    def test_total_cap_checked_first(self):
        r = engine.evaluate(_ctx(counts={"total": 40, "web_reads": 10}))
        assert r.effect == E.PolicyEffect.THROTTLE
        assert r.reason_code == E.PolicyReason.DAILY_CAP_REACHED

    def test_unknown_action_default_deny(self):
        r = engine.evaluate(_ctx(action_type="social.follow"))
        assert r.effect == E.PolicyEffect.DENY
        assert E.PolicyReason.UNKNOWN_ACTION_TYPE in r.reason_codes

    def test_approval_satisfied_only_for_same_hash(self):
        ch = engine.Channel("c1", "LINKEDIN", "active", "SET",
                            frozenset({"content.publish_approved"}))
        kw = dict(action_type="channel.post.create", payload={"text": "x"}, channel=ch,
                  trust={"content.publish_approved": E.TrustLevel.L1},
                  grants=frozenset({"content.publish_approved"}), content_hash="h1")
        assert engine.evaluate(_ctx(**kw)).effect == E.PolicyEffect.REQUIRE_APPROVAL
        assert engine.evaluate(_ctx(**kw, approved_hash="other")).effect == \
            E.PolicyEffect.REQUIRE_APPROVAL
        ok = engine.evaluate(_ctx(**kw, approved_hash="h1"))
        assert ok.effect == E.PolicyEffect.ALLOW and ok.reason_code == E.PolicyReason.APPROVED


# ---------------------------------------------------------------- tok akcije


@pytest.mark.django_db
class TestFlow:
    def test_read_allowed_queued_and_gateway_is_dry_run(self, mila):
        pr = _propose(mila, "browser.page.read", _read())
        a = pr.action
        assert a.status == E.ActionStatus.QUEUED and pr.decision.effect == "ALLOW"
        assert pr.decision.policy_version and pr.decision.expires_at
        c = gateway.authorize(a)
        assert c["dry_run"] is True  # GLOBAL_EXTERNAL_ACTIONS_ENABLED=false
        assert c["execution_constraints"]["robots_respected"] is True
        assert c["policy_decision_id"] == pr.decision.public_id
        types = set(EventOutbox.objects.values_list("event_type", flat=True))
        assert {"action.proposed", "policy.decision.created", "action.queued"} <= types

    def test_read_without_constraints_denied(self, mila):
        pr = _propose(mila, "browser.page.read", {"url": "https://example.com"})
        assert pr.action.status == E.ActionStatus.BLOCKED
        assert pr.decision.reason_code == E.PolicyReason.READ_CONSTRAINTS_MISSING

    def test_same_proposal_is_idempotent(self, mila):
        a = _propose(mila, "browser.page.read", _read(1))
        b = _propose(mila, "browser.page.read", _read(1))
        assert a.action.pk == b.action.pk and b.created is False

    def test_publish_needs_trust_then_approval(self, mila, page):
        low = Persona.objects.get(pk=mila.pk)
        with bind(actor_id="user:ts"):
            service.change_trust(low, "content.publish_approved", E.TrustLevel.L0,
                                 actor="user:ts", reason="test")
        denied = _propose(mila, "channel.post.create", {"text": "Prva objava"}, channel=page)
        assert E.PolicyReason.TRUST_TOO_LOW in denied.decision.reason_codes
        with bind(actor_id="user:ts"):
            service.change_trust(low, "content.publish_approved", E.TrustLevel.L1,
                                 actor="user:ts", reason="QA")
        pr = _propose(mila, "channel.post.create", {"text": "Druga objava"}, channel=page)
        assert pr.decision.effect == "REQUIRE_APPROVAL" and pr.approval.approval_class == "A2"
        assert pr.approval.payload_hash == pr.action.content_hash
        assert pr.approval.expires_at - pr.decision.evaluated_at == timedelta(hours=2)
        assert pr.action.status == E.ActionStatus.APPROVAL_PENDING
        with pytest.raises(gateway.GatewayRefused):
            gateway.authorize(pr.action)  # nije QUEUED

    def test_approve_requeues_with_new_decision(self, mila, page):
        pr = _propose(mila, "channel.post.create", {"text": "Objava za odobrenje"}, channel=page)
        with bind(actor_id="user:op"):
            service.decide_approval(pr.approval, E.ApprovalStatus.APPROVED, actor="user:op",
                                    role=E.Role.OPERATOR, reason="ok")
        a = Action.objects.get(pk=pr.action.pk)
        assert a.status == E.ActionStatus.QUEUED
        assert a.policy_decision.reason_codes[0] == E.PolicyReason.APPROVED
        assert a.decisions.count() == 2
        c = gateway.authorize(a)
        assert c["approval_id"] == pr.approval.public_id and c["dry_run"] is True

    def test_second_decision_conflicts(self, mila, page):
        pr = _propose(mila, "channel.post.create", {"text": "Dvostruko"}, channel=page)
        with bind(actor_id="user:op"):
            service.decide_approval(pr.approval, E.ApprovalStatus.APPROVED, actor="user:op",
                                    role=E.Role.OPERATOR)
            with pytest.raises(service.PolicyError) as e:
                service.decide_approval(pr.approval, E.ApprovalStatus.REJECTED, actor="user:x",
                                        role=E.Role.OPERATOR)
        assert e.value.code == "VERSION_CONFLICT"

    def test_approved_with_changes_rehashes_and_rechecks(self, mila, page):
        pr = _propose(mila, "channel.post.create", {"text": "Dugačak hook"}, channel=page)
        old_hash = pr.action.content_hash
        with bind(actor_id="user:op"):
            ap = service.decide_approval(pr.approval, E.ApprovalStatus.APPROVED_WITH_CHANGES,
                                         actor="user:op", role=E.Role.OPERATOR,
                                         reason="skraćen hook",
                                         payload_override={"text": "Kratak hook"})
        a = Action.objects.get(pk=pr.action.pk)
        assert a.content_hash != old_hash and ap.payload_hash == a.content_hash
        assert a.status == E.ActionStatus.QUEUED
        gateway.authorize(a)

    def test_changes_are_screened_by_guards(self, mila, page):
        pr = _propose(mila, "channel.post.create", {"text": "Normalna objava"}, channel=page)
        with bind(actor_id="user:op"):
            service.decide_approval(pr.approval, E.ApprovalStatus.APPROVED_WITH_CHANGES,
                                    actor="user:op", role=E.Role.OPERATOR,
                                    payload_override={"text": "Ja sam prava osoba, nisam AI"})
        a = Action.objects.get(pk=pr.action.pk)
        assert a.status == E.ActionStatus.BLOCKED
        assert Persona.objects.get(pk=mila.pk).status == E.PersonaStatus.SUSPENDED

    def test_reject_cancels(self, mila, page):
        pr = _propose(mila, "channel.post.create", {"text": "Ne"}, channel=page)
        with bind(actor_id="user:op"):
            service.decide_approval(pr.approval, E.ApprovalStatus.REJECTED, actor="user:op",
                                    role=E.Role.OPERATOR, reason="ne sad")
        assert Action.objects.get(pk=pr.action.pk).status == E.ActionStatus.CANCELLED

    def test_expiry_by_class(self, mila, page, mailbox):
        post = _propose(mila, "channel.post.create", {"text": "A2"}, channel=page)
        mail = _propose(mila, "mail.send", {"text": "Poštovani", "to": "info@firma.test"},
                        channel=mailbox, target_ref="info@firma.test")
        assert mail.approval.approval_class == "A1"
        later = timezone.now() + timedelta(hours=5)
        with bind(actor_id="service:policy"):
            assert service.expire_approvals(later) == 2
            with pytest.raises(service.PolicyError):
                service.decide_approval(post.approval, E.ApprovalStatus.APPROVED,
                                        actor="user:op", role=E.Role.OPERATOR)
        assert Action.objects.get(pk=post.action.pk).status == E.ActionStatus.EXPIRED
        assert Action.objects.get(pk=mail.action.pk).status == E.ActionStatus.CANCELLED

    def test_gateway_refuses_changed_payload(self, mila):
        a = _propose(mila, "browser.page.read", _read(2)).action
        Action.objects.filter(pk=a.pk).update(input_json={**a.input_json, "url": "https://x"})
        with pytest.raises(gateway.GatewayRefused) as e:
            gateway.authorize(a)
        assert e.value.reason_code == "PAYLOAD_CHANGED"
        assert Action.objects.get(pk=a.pk).status == E.ActionStatus.BLOCKED

    def test_fail_closed(self, mila, monkeypatch):
        def boom(ctx):
            raise RuntimeError("policy down")
        monkeypatch.setattr(engine, "evaluate", boom)
        pr = _propose(mila, "browser.page.read", _read(3))
        assert pr.decision.effect == "DENY" and pr.decision.fail_closed is True
        assert pr.action.status == E.ActionStatus.BLOCKED

    @override_settings(GLOBAL_EXTERNAL_ACTIONS_ENABLED=True)
    def test_live_only_when_flag_and_environment_allow(self, mila):
        a = _propose(mila, "browser.page.read", _read(4)).action
        assert gateway.authorize(a)["dry_run"] is True  # persona je u SIMULATION
        Persona.objects.filter(pk=mila.pk).update(
            runtime_environment=E.RuntimeEnvironment.CONTROLLED_LIVE)
        b = _propose(mila, "browser.page.read", _read(5)).action
        assert gateway.authorize(b)["dry_run"] is False


# ---------------------------------------------------------------- tvrde zabrane


@pytest.mark.django_db
def test_hard_prohibition_suspends_and_opens_sev1(mila, page):
    pr = _propose(mila, "channel.post.create",
                  {"text": "Ne brinite, ja sam stvarna osoba"}, channel=page)
    assert pr.decision.effect == "DENY"
    assert pr.decision.reason_code == E.PolicyReason.HARD_PROHIBITION
    inc = PolicyIncident.objects.get(action=pr.action)
    assert inc.severity == "SEV1" and inc.summary == "IDENTITY_IMPERSONATION"
    assert Persona.objects.get(pk=mila.pk).status == E.PersonaStatus.SUSPENDED
    ts = TrustState.objects.get(persona=mila, capability="content.publish_approved")
    assert ts.level == "L0" and ts.auto_downgrade_count == 1
    assert not CapabilityGrant.objects.filter(persona=mila, capability="content.publish_approved",
                                              revoked_at__isnull=True).exists()
    after = _propose(mila, "browser.page.read", _read(9))
    assert E.PolicyReason.PERSONA_NOT_OPERATIONAL in after.decision.reason_codes
    types = set(EventOutbox.objects.values_list("event_type", flat=True))
    assert {"policy.incident.opened", "trust.level.changed", "action.blocked"} <= types


# ---------------------------------------------------------------- limiti


@pytest.mark.django_db
def test_daily_total_cap_is_hard_ceiling(mila):
    for i in range(40):
        assert _propose(mila, "browser.page.read", _read(100 + i)).decision.effect == "ALLOW"
    over = _propose(mila, "browser.page.read", _read(999))
    assert over.decision.effect == "THROTTLE"
    assert over.decision.reason_code == E.PolicyReason.DAILY_CAP_REACHED
    assert _propose(mila, "content.draft", {"text": "interno"}).decision.effect == "ALLOW"


@requires_db
@pytest.mark.django_db(transaction=True)
def test_parallel_proposals_never_exceed_cap():
    """Policy v0.1 §19 — atomičnost kvote: 36 potrošeno, 8 paralelnih → tačno 4 prolaze."""
    call_command("seed_agent_001", stdout=io.StringIO())
    p = Persona.objects.get(public_id="P-00001")
    for i in range(36):
        _propose(p, "browser.page.read", _read(200 + i))
    effects: list[str] = []
    barrier = threading.Barrier(8)

    def worker(i):
        try:
            barrier.wait()
            effects.append(_propose(p, "browser.page.read", _read(300 + i)).decision.effect)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(effects).count("ALLOW") == 4 and effects.count("THROTTLE") == 4


# ---------------------------------------------------------------- kill-switch


@pytest.mark.django_db
class TestKillSwitch:
    def test_global_stop_blocks_open_actions_and_new_ones(self, mila, page):
        queued = _propose(mila, "browser.page.read", _read(10)).action
        pending = _propose(mila, "channel.post.create", {"text": "čeka"}, channel=page)
        with bind(actor_id="user:op"):
            ks = service.activate_kill_switch(E.KillSwitchScope.GLOBAL, "", reason="drill",
                                              actor="user:op")
        assert Action.objects.get(pk=queued.pk).status == E.ActionStatus.BLOCKED
        assert Action.objects.get(pk=pending.action.pk).status == E.ActionStatus.BLOCKED
        assert ApprovalRequest.objects.get(pk=pending.approval.pk).status == "CANCELLED"
        assert ks.stop_latency_ms is not None and ks.stop_latency_ms < 30_000
        new = _propose(mila, "browser.page.read", _read(11))
        assert new.decision.reason_code == E.PolicyReason.KILL_SWITCH_ACTIVE
        with bind(actor_id="user:ts"):
            service.release_kill_switch(ks, actor="user:ts", reason="drill gotov")
        assert Action.objects.get(pk=queued.pk).status == E.ActionStatus.BLOCKED  # ostaje
        assert _propose(mila, "browser.page.read", _read(12)).decision.effect == "ALLOW"

    def test_gateway_rechecks_kill_switch(self, mila):
        a = _propose(mila, "browser.page.read", _read(13)).action
        KillSwitch.objects.create(scope="CAPABILITY", target_ref="web.read_public",
                                  reason="direktno", activated_by="user:x",
                                  activated_at=timezone.now())
        with pytest.raises(gateway.GatewayRefused) as e:
            gateway.authorize(a)
        assert e.value.reason_code == E.PolicyReason.KILL_SWITCH_ACTIVE

    def test_persona_scope_only_hits_that_persona(self, mila):
        a = _propose(mila, "browser.page.read", _read(14)).action
        with bind(actor_id="user:op"):
            service.activate_kill_switch(E.KillSwitchScope.PERSONA, "P-00002",
                                         reason="druga", actor="user:op")
        assert Action.objects.get(pk=a.pk).status == E.ActionStatus.QUEUED


# ---------------------------------------------------------------- poverenje


@pytest.mark.django_db
class TestTrust:
    def test_reserved_levels_refused(self, mila):
        with pytest.raises(service.PolicyError):
            service.change_trust(mila, "content.publish_approved", E.TrustLevel.L3,
                                 actor="user:ts", reason="x")

    def test_unknown_capability_refused(self, mila):
        with pytest.raises(service.PolicyError):
            service.change_trust(mila, "social.first_dm", E.TrustLevel.L1,  # canon-lint: allow
                                 actor="user:ts", reason="x")

    def test_grant_follows_trust(self, mila):
        with bind(actor_id="user:ts"):
            service.change_trust(mila, "social.reply_inbound", E.TrustLevel.L2,
                                 actor="user:ts", reason="stabilno")
            assert CapabilityGrant.objects.filter(persona=mila, capability="social.reply_inbound",
                                                  revoked_at__isnull=True).exists()
            service.change_trust(mila, "social.reply_inbound", E.TrustLevel.L1,
                                 actor="user:ts", reason="pad")
        assert not CapabilityGrant.objects.filter(persona=mila, capability="social.reply_inbound",
                                                  revoked_at__isnull=True).exists()


# ---------------------------------------------------------------- invarijanta


@pytest.mark.django_db
def test_no_queued_action_without_allow(mila, page):
    """Policy v0.1 §19 — property: nijedan DENY/THROTTLE/APPROVAL ne postaje izvršiv."""
    samples = [("browser.page.read", _read(i)) for i in range(15)] + [
        ("browser.page.read", {"url": "bez parametara"}),
        ("channel.post.create", {"text": "objava"}),
        ("channel.post.create", {"text": "nisam AI"}),
        ("mail.send", {"text": "x"}),
        ("social.follow", {}),
        ("content.draft", {"text": "nacrt"}),
    ]
    for at, pl in samples:
        _propose(mila, at, pl, channel=page if at.startswith("channel.") else None)
    for a in Action.objects.filter(status=E.ActionStatus.QUEUED):
        assert a.policy_decision.effect == "ALLOW"
    for d in PolicyDecision.objects.exclude(effect="ALLOW"):
        assert d.action.status != E.ActionStatus.QUEUED


# ---------------------------------------------------------------- API


def _client(name, *roles):
    u = User.objects.create_user(username=name)
    for r in roles:
        u.groups.add(Group.objects.get(name=r.value))
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}")
    return c


def _h(actor, key=None):
    h = {"HTTP_X_REQUEST_ID": f"req-{key or 'read'}-abc", "HTTP_X_ACTOR_ID": actor,
         "HTTP_TRACEPARENT": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
    if key:
        h["HTTP_IDEMPOTENCY_KEY"] = key
    return h


@pytest.mark.django_db
class TestPolicyApi:
    def test_propose_approve_flow(self, mila, page):
        op = _client("op", E.Role.OPERATOR)
        r = op.post("/api/v1/actions/propose", {
            "persona_id": "P-00001", "action_type": "channel.post.create",
            "payload": {"text": "API objava"}, "channel_account_id": str(page.id),
        }, format="json", **_h("user:op", "prop-key-001"))
        assert r.status_code == 201, r.content
        body = r.json()["data"]
        assert body["decision"]["effect"] == "REQUIRE_APPROVAL"
        assert body["decision"]["zone"] == "YELLOW"
        apr = body["approval"]["approval_id"]
        lst = op.get("/api/v1/approvals").json()["data"]
        assert [a["approval_id"] for a in lst] == [apr]
        d = op.post(f"/api/v1/approvals/{apr}/decision", {"decision": "APPROVED", "reason": "ok"},
                    format="json", **_h("user:op", "dec-key-001"))
        assert d.status_code == 200, d.content
        assert d.json()["data"]["action"]["status"] == "QUEUED"

    def test_viewer_cannot_decide(self, mila, page):
        pr = _propose(mila, "channel.post.create", {"text": "v"}, channel=page)
        v = _client("vv", E.Role.VIEWER)
        r = v.post(f"/api/v1/approvals/{pr.approval.public_id}/decision",
                   {"decision": "APPROVED"}, format="json", **_h("user:vv", "dec-key-002"))
        assert r.status_code == 403

    def test_dry_run_evaluate_writes_nothing(self, mila):
        c = _client("rd", E.Role.OPERATOR)
        before = Action.objects.count()
        r = c.post("/api/v1/policy/evaluate", {"persona_id": "P-00001",
                                                "action_type": "browser.page.read",
                                                "payload": _read(50)},
                   format="json", **_h("user:rd"))
        assert r.status_code == 200, r.content
        data = r.json()["data"]
        assert data["decision_id"] is None and data["dry_run"] is True
        assert data["effect"] == "ALLOW" and Action.objects.count() == before
        b = c.post("/api/v1/policy/evaluate/batch", {"items": [
            {"persona_id": "P-00001", "action_type": "social.follow"},
            {"persona_id": "P-00001", "action_type": "content.draft", "payload": {"text": "x"}},
        ]}, format="json", **_h("user:rd"))
        assert [x["effect"] for x in b.json()["data"]] == ["DENY", "ALLOW"]

    def test_kill_switch_roles(self, mila):
        op = _client("op2", E.Role.OPERATOR)
        r = op.post("/api/v1/kill-switches", {"scope": "GLOBAL", "reason": "vežba"},
                    format="json", **_h("user:op2", "ks-key-001"))
        assert r.status_code == 201, r.content
        ks_id = r.json()["data"]["kill_switch_id"]
        clear = op.post("/api/v1/kill-switches", {"operation": "clear", "kill_switch_id": ks_id,
                                                  "reason": "kraj"},
                        format="json", **_h("user:op2", "ks-key-002"))
        assert clear.status_code == 403
        ts = _client("ts", E.Role.TRUST_SAFETY)
        ok = ts.post("/api/v1/kill-switches", {"operation": "clear", "kill_switch_id": ks_id,
                                               "reason": "kraj"},
                     format="json", **_h("user:ts", "ks-key-003"))
        assert ok.status_code == 200 and ok.json()["data"]["is_active"] is False

    def test_trust_change_api(self, mila):
        ts = _client("ts2", E.Role.TRUST_SAFETY)
        r = ts.post("/api/v1/personas/P-00001/trust/change",
                    {"capability": "content.publish_approved", "level": "L1", "reason": "QA"},
                    format="json", **_h("user:ts2", "tr-key-001"))
        assert r.status_code == 200, r.content
        body = r.json()["data"]
        assert body["trust"]["content.publish_approved"] == "L1"
        assert body["display_level"] == "L0"  # minimum po capability-jima
        bad = ts.post("/api/v1/personas/P-00001/trust/change",
                      {"capability": "content.publish_approved", "level": "L3", "reason": "x"},
                      format="json", **_h("user:ts2", "tr-key-002"))
        assert bad.status_code == 400
        op = _client("op3", E.Role.OPERATOR)
        forbidden = op.post("/api/v1/personas/P-00001/trust/change",
                            {"capability": "content.publish_approved", "level": "L1",
                             "reason": "x"}, format="json", **_h("user:op3", "tr-key-003"))
        assert forbidden.status_code == 403

    def test_incidents_visible(self, mila, page):
        _propose(mila, "channel.post.create", {"text": "ja sam prava osoba"}, channel=page)
        c = _client("aud", E.Role.TRUST_SAFETY)
        data = c.get("/api/v1/policy/incidents").json()["data"]
        assert data and data[0]["severity"] == "SEV1"
