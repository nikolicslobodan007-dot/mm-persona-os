"""F6 — Runtime: izvršenje, adapteri, retry, reconcile, breaker, odjava. ADR-0008.

Invarijante (Canon §6.2, §9.6, §12, §16.4–16.5):
  - bez ALLOW nema posla; interne akcije ne idu u red;
  - dry_run ugovor NIKAD ne dodiruje spoljni sistem, i druga brava u
    transportu odbija slanje dok je globalni prekidač isključen;
  - tajna nikad ne ulazi u bazu ni u evidenciju — samo `credential_ref`;
  - UNKNOWN_EFFECT nikad ne vodi u retry, nego u reconcile;
  - kill-switch zaustavlja akciju u letu između dva zahteva;
  - kanal bez sankcionisanog puta daje CAPABILITY_UNAVAILABLE, ne grešku;
  - odjava kod jedne persone važi za sve.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.context import bind
from apps.channels import suppression
from apps.channels.models import ChannelAccount, ChannelCapability, SuppressionEntry
from apps.observability.models import CostLedger, EventOutbox
from apps.orchestration.models import Action
from apps.personas.models import Persona
from apps.policy import service
from apps.policy.models import KillSwitch, PolicyIncident
from apps.runtime import breaker, executor
from apps.runtime.adapters import resolve
from apps.runtime.adapters.mail import mailbox_cap
from apps.runtime.adapters.social import similarity
from apps.runtime.models import CircuitBreaker, ReconcileTask, RuntimeSession, WorkerJob
from apps.runtime.transport import (
    DryRunTransport,
    ExternalActionsDisabled,
    LiveTransport,
    Request,
    Response,
    TransportError,
)
from common import enums as E
from tests.conftest import _propose, _read, requires_db

pytestmark = [requires_db]
OC = E.ExecutionOutcome
S = E.ActionStatus


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------- pomoćno


def _account(persona, channel_type, vehicle, caps, *, label=E.DisclosureLabelStatus.SET,
             **kw) -> ChannelAccount:
    acc = ChannelAccount.objects.create(
        persona=persona, channel_type=channel_type, identity_vehicle=vehicle,
        handle=kw.pop("handle", f"mila-{channel_type.value.lower()}"),
        status=E.AccountStatus.ACTIVE, disclosure_label_status=label,
        credential_ref=kw.pop("credential_ref", "env:TEST_CHANNEL_TOKEN"), **kw)
    for cap, level in caps.items():
        ChannelCapability.objects.create(account=acc, capability=cap, is_enabled=True,
                                         source="policy",
                                         evidence_level=E.EvidenceLevel.RESPONSE_ONLY)
        current = service.trust_map(Persona.objects.get(pk=persona.pk)).get(cap,
                                                                            E.TrustLevel.L0)
        if current.value < level.value:
            with bind(actor_id="user:ts"):
                service.change_trust(persona, cap, level, actor="user:ts", reason="QA")
    return acc


def _go(pr) -> Action:
    """Odobri ako treba; vrati akciju u QUEUED."""
    if pr.approval is not None:
        with bind(actor_id="user:op"):
            service.decide_approval(pr.approval, E.ApprovalStatus.APPROVED, actor="user:op",
                                    role=E.Role.OPERATOR, reason="QA")
    a = Action.objects.get(pk=pr.action.pk)
    assert a.status == S.QUEUED, (a.status, a.error_code, a.policy_decision.reason_codes)
    return a


def _job(a: Action) -> WorkerJob:
    return WorkerJob.objects.filter(action=a).order_by("-created_at").first()


def _run(a: Action, **kw) -> Action:
    executor.execute_job(_job(a).pk, **kw)
    return Action.objects.get(pk=a.pk)


def _live(persona):
    Persona.objects.filter(pk=persona.pk).update(
        runtime_environment=E.RuntimeEnvironment.CONTROLLED_LIVE)


class FakeLive:
    """Skriptovan „živi" transport — ništa ne ide na mrežu."""

    live = True

    def __init__(self, *script):
        self.script, self.sent = list(script), []

    def send(self, req, *, credential_ref=""):
        self.sent.append(req)
        r = self.script.pop(0) if self.script else Response(200, json={"id": "ok"})
        if callable(r):
            r = r(req)
        if isinstance(r, Exception):
            raise r
        return r


def _factory(t):
    return lambda dry: t


@pytest.fixture
def sandbox(mila):
    return _account(mila, E.ChannelType.SANDBOX, E.IdentityVehicle.SANDBOX,
                    {"content.publish_approved": E.TrustLevel.L1,
                     "social.reply_inbound": E.TrustLevel.L2},
                    label=E.DisclosureLabelStatus.NOT_REQUIRED, handle="mila-sb-f6")


@pytest.fixture
def x_acc(mila):
    return _account(mila, E.ChannelType.X, E.IdentityVehicle.PROFILE,
                    {"content.publish_approved": E.TrustLevel.L1,
                     "social.reply_inbound": E.TrustLevel.L2,
                     "social.read_public": E.TrustLevel.L0},
                    provider_account_id="1234")


@pytest.fixture
def ig(mila):
    return _account(mila, E.ChannelType.INSTAGRAM, E.IdentityVehicle.PROFILE,
                    {"content.publish_approved": E.TrustLevel.L1},
                    provider_account_id="17841400000000000")


@pytest.fixture
def mail_ready(mailbox):
    ChannelAccount.objects.filter(pk=mailbox.pk).update(
        sending_domain="mila-posta.rs", persona_address="mila@persone.rs",
        warmup_started_at=timezone.now() - timedelta(days=30), daily_cap=20)
    return ChannelAccount.objects.get(pk=mailbox.pk)


# ---------------------------------------------------------------- red


class TestQueue:
    def test_allow_creates_exactly_one_job(self, mila):
        pr = _propose(mila, "browser.page.read", _read(1))
        a = _go(pr)
        job = _job(a)
        assert job.status == E.JobStatus.PENDING and job.queue == E.QueueName.BROWSER
        assert job.max_attempts == 3  # čitanje (Canon §12.4)
        assert executor.enqueue(a) == job
        assert WorkerJob.objects.filter(action=a).count() == 1

    def test_no_job_before_approval(self, mila, page):
        pr = _propose(mila, "channel.post.create", {"text": "Čeka odobrenje"}, channel=page)
        assert pr.action.status == S.APPROVAL_PENDING
        assert not WorkerJob.objects.filter(action=pr.action).exists()
        a = _go(pr)
        assert _job(a).max_attempts == 2  # pisanje

    def test_denied_never_queued(self, mila, page):
        pr = _propose(mila, "channel.post.create", {"text": "Ja sam prava osoba"}, channel=page)
        assert pr.action.status == S.BLOCKED
        assert not WorkerJob.objects.filter(action=pr.action).exists()

    def test_job_for_non_queued_action_is_dropped(self, mila):
        a = _go(_propose(mila, "browser.page.read", _read(2)))
        Action.objects.filter(pk=a.pk).update(status=S.BLOCKED)
        job = executor.execute_job(_job(a).pk)
        assert job.status == E.JobStatus.FAILED
        assert not a.attempts.exists()


# ---------------------------------------------------------------- dry-run


class TestDryRun:
    def test_linkedin_post_dry_run_shows_request_without_secret(self, mila, page,
                                                                 monkeypatch):
        monkeypatch.setenv("SECRET_LI", "tajna-vrednost-123")
        ChannelAccount.objects.filter(pk=page.pk).update(credential_ref="env:SECRET_LI",
                                                         provider_account_id="98765")
        a = _go(_propose(mila, "channel.post.create", {"text": "Nova objava sa sajta"},
                         channel=page))
        a = _run(a)
        assert a.status == S.SUCCEEDED
        assert a.result_json["dry_run"] is True and a.result_json["external_ref"] is None
        att = a.attempts.get()
        assert att.outcome == OC.SUCCEEDED and att.reason_code == "DRY_RUN"
        assert att.evidence_level == E.EvidenceLevel.NONE
        req = att.payload["requests"][0]
        assert req["method"] == "POST" and req["url"].endswith("/rest/posts")
        assert req["headers"]["LinkedIn-Version"] == "202608"
        assert req["json"]["author"] == "urn:li:organization:98765"
        assert req["headers"]["Authorization"] == "Bearer ‹credential_ref›"
        dump = json.dumps([att.payload, a.result_json], ensure_ascii=False)
        assert "tajna-vrednost-123" not in dump
        types = list(EventOutbox.objects.values_list("event_type", flat=True))
        for t in ("runtime.execution.started", "action.succeeded",
                  "runtime.execution.finished"):
            assert t in types
        assert not CostLedger.objects.exists()
        assert RuntimeSession.objects.get().status == E.SessionStatus.CLOSED

    def test_x_post_estimates_cost_but_records_none(self, mila, x_acc):
        a = _go(_propose(mila, "channel.post.create",
                         {"text": "Pogledajte https://primer.rs novi tekst"}, channel=x_acc))
        a = _run(a)
        att = a.attempts.get()
        assert a.status == S.SUCCEEDED and att.payload["estimated_cost_usd"] == "0.20"
        assert not CostLedger.objects.exists()

    def test_sandbox_runs_without_external_system(self, mila, sandbox):
        a = _run(_go(_propose(mila, "channel.post.create", {"text": "Sandbox objava"},
                              channel=sandbox)))
        assert a.status == S.SUCCEEDED
        assert a.result_json["external_ref"].startswith("sandbox:")
        assert a.attempts.get().payload["requests"] == []

    def test_second_lock_in_transport(self, mila, page):
        """I kad bi neko predao ugovor bez dry_run-a, transport odbija dok je prekidač off."""
        with pytest.raises(ExternalActionsDisabled):
            LiveTransport().send(Request("POST", "https://api.linkedin.com/rest/posts"))
        sent = []

        class Spy(LiveTransport):
            def _http(self, req, credential_ref):  # pragma: no cover — ne sme se pozvati
                sent.append(req)
                return Response(200)

        ChannelAccount.objects.filter(pk=page.pk).update(provider_account_id="555")
        a = _go(_propose(mila, "channel.post.create", {"text": "Druga brava"}, channel=page))
        a = _run(a, transport_factory=lambda dry: Spy())
        assert sent == []
        assert a.status == S.BLOCKED
        assert a.attempts.get().reason_code == "EXTERNAL_ACTIONS_DISABLED"

    def test_instagram_needs_media(self, mila, ig):
        a = _run(_go(_propose(mila, "channel.post.create", {"text": "Samo tekst"}, channel=ig)))
        assert a.status == S.FAILED and a.error_code == "MEDIA_REQUIRED"

    def test_instagram_two_step_publish(self, mila, ig):
        a = _run(_go(_propose(mila, "channel.post.create",
                              {"text": "Slika dana", "image_url": "https://cdn.test/1.jpg"},
                              channel=ig)))
        urls = [r["url"] for r in a.attempts.get().payload["requests"]]
        assert urls[0].endswith("/17841400000000000/media")
        assert urls[1].endswith("/17841400000000000/media_publish")
        assert "graph.instagram.com/v25.0" in urls[0]


# ---------------------------------------------------------------- matrica


class TestCapabilityMatrix:
    @pytest.mark.parametrize("channel, action", [
        ("LINKEDIN", "channel.read.public"),
        ("FACEBOOK", "channel.read.public"),
        ("X", "channel.comment.moderate"),
    ])
    def test_unavailable_is_named(self, channel, action):
        adapter, code, why = resolve(channel, action)
        assert adapter is None and code == "UNSUPPORTED" and why

    def test_no_social_channel_uses_a_browser(self):
        for ch in ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "X"):
            for at in ("channel.post.create", "channel.comment.create"):
                adapter, _, _ = resolve(ch, at)
                assert adapter.key not in ("web",)

    def test_out_of_scope_channels_have_no_adapter(self):
        assert resolve("TIKTOK", "channel.post.create")[0] is None
        assert resolve("YOUTUBE", "channel.post.create")[0] is None

    def test_unavailable_action_is_cancelled_not_failed(self, mila, x_acc):
        a = _go(_propose(mila, "channel.comment.moderate", {"hide": True},
                         target_ref="1111", channel=x_acc))
        a = _run(a)
        assert a.status == S.CANCELLED
        att = a.attempts.get()
        assert att.outcome == OC.CAPABILITY_UNAVAILABLE and att.reason_code == "UNSUPPORTED"

    def test_linkedin_requires_named_admin(self, mila, page):
        ChannelAccount.objects.filter(pk=page.pk).update(named_human_admin="",
                                                         provider_account_id="1")
        a = _run(_go(_propose(mila, "channel.post.create", {"text": "Bez admina"},
                              channel=page)))
        assert a.status == S.BLOCKED and a.error_code == "NAMED_ADMIN_MISSING"


# ---------------------------------------------------------------- X ponavljanje


class TestRepetitionGuard:
    def test_similarity(self):
        assert similarity("Danas je lep dan za šetnju po gradu",
                          "Danas je lep dan za setnju po gradu!") == 1.0
        assert similarity("Novi proizvod u ponudi", "Sutra zatvaramo ranije") == 0.0

    def test_second_similar_post_is_denied(self, mila, x_acc):
        text = "Stigla je nova kolekcija drvenih kutija za vino, pogledajte ponudu"
        first = _run(_go(_propose(mila, "channel.post.create", {"text": text},
                                  channel=x_acc)))
        assert first.status == S.SUCCEEDED
        second = _run(_go(_propose(mila, "channel.post.create", {"text": text + "!"},
                                   channel=x_acc)))
        assert second.status == S.BLOCKED and second.error_code == "REPETITION_GUARD"


# ---------------------------------------------------------------- pošta


class TestMail:
    def _send(self, mila, acc, to="info@firma.test", text="Poštovani, šaljemo ponudu."):
        return _go(_propose(mila, "mail.send", {"text": text, "to": to, "subject": "Ponuda"},
                            channel=acc))

    def test_message_has_one_click_unsubscribe(self, mila, mail_ready):
        a = _run(self._send(mila, mail_ready))
        assert a.status == S.SUCCEEDED
        req = a.attempts.get().payload["requests"][0]
        assert req["kind"] == "smtp" and req["headers"]["From"] == "mila@mila-posta.rs"
        from email import message_from_string, policy

        msg = message_from_string(req["body"], policy=policy.default)
        assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        assert "/api/v1/mail/unsubscribe?t=" in str(msg["List-Unsubscribe"])
        assert msg["Reply-To"] == "mila@persone.rs"
        assert "(AI)" in str(msg["From"]) or msg["From"].addresses[0].addr_spec
        assert "info@firma.test" not in json.dumps(a.result_json)

    def test_suppressed_recipient_blocked_for_every_persona(self, mila, mail_ready):
        suppression.suppress("Info@Firma.test ", E.SuppressionReason.UNSUBSCRIBE,
                             source="test")
        a = _run(self._send(mila, mail_ready))
        assert a.status == S.BLOCKED and a.error_code == "SUPPRESSED"
        assert not SuppressionEntry.objects.filter(address_hash="").exists()
        assert "info@firma.test" not in json.dumps(
            list(SuppressionEntry.objects.values()), default=str)

    def test_domain_suppression(self, mila, mail_ready):
        suppression.suppress_domain("firma.test", source="test")
        a = _run(self._send(mila, mail_ready, to="prodaja@firma.test"))
        assert a.error_code == "SUPPRESSED"

    def test_never_from_primary_domain(self, mila, mail_ready):
        ChannelAccount.objects.filter(pk=mail_ready.pk).update(
            sending_domain="posta.webkorporacija.com")
        a = _run(self._send(mila, mail_ready))
        assert a.status == S.BLOCKED and a.error_code == "PRIMARY_DOMAIN_OUTBOUND"

    def test_max_three_mailboxes_per_domain(self, mila, mail_ready):
        for i in range(3):
            ChannelAccount.objects.create(
                persona=mila, channel_type=E.ChannelType.EMAIL,
                identity_vehicle=E.IdentityVehicle.NEWSLETTER, handle=f"x{i}@mila-posta.rs",
                status=E.AccountStatus.ACTIVE, sending_domain="mila-posta.rs",
                disclosure_label_status=E.DisclosureLabelStatus.NOT_REQUIRED)
        a = _run(self._send(mila, mail_ready))
        assert a.error_code == "TOO_MANY_MAILBOXES"

    def test_warmup_ramp(self, mail_ready):
        now = timezone.now()
        mail_ready.warmup_started_at = None
        assert mailbox_cap(mail_ready, now) == 5
        mail_ready.warmup_started_at = now - timedelta(days=10)
        assert 5 < mailbox_cap(mail_ready, now) < 20
        mail_ready.warmup_started_at = now - timedelta(days=21)
        assert mailbox_cap(mail_ready, now) == 20

    def test_unsubscribe_link_flow(self, db):
        c = APIClient()
        url = suppression.unsubscribe_url("kupac@primer.rs")
        path = url.split("os.webkorporacija.com", 1)[1]
        r = c.get(path)
        assert r.status_code == 200 and b"Odjavi me" in r.content
        assert not suppression.is_suppressed("kupac@primer.rs")  # GET ne odjavljuje
        token = path.split("t=", 1)[1]
        r = c.post(path, {"List-Unsubscribe": "One-Click"})
        assert r.status_code == 200, r.content
        assert suppression.is_suppressed("KUPAC@primer.rs")
        assert SuppressionEntry.objects.get().source == "one_click"
        assert c.post("/api/v1/mail/unsubscribe", {"t": token + "x"}).status_code == 400


# ---------------------------------------------------------------- živi tok (lažna mreža)


class TestLiveFlow:
    @pytest.fixture(autouse=True)
    def _switch_on(self, settings):
        settings.GLOBAL_EXTERNAL_ACTIONS_ENABLED = True

    def test_success_records_cost_and_ref(self, mila, x_acc):
        _live(mila)
        t = FakeLive(Response(201, json={"data": {"id": "1799"}}))
        a = _run(_go(_propose(mila, "channel.post.create", {"text": "Živa objava"},
                              channel=x_acc)), transport_factory=_factory(t))
        assert a.status == S.SUCCEEDED and a.result_json["external_ref"] == "1799"
        assert t.sent[0].auth == "bearer" and "Authorization" not in t.sent[0].headers
        cost = CostLedger.objects.get()
        assert cost.cost_bucket == E.CostBucket.X_API_CREDITS and cost.amount_eur_cents == 2
        assert a.attempts.get().evidence_level == E.EvidenceLevel.RESPONSE_ONLY

    def test_429_retries_then_fails(self, mila):
        _live(mila)
        a = _go(_propose(mila, "browser.page.read", _read(3)))
        robots = Response(200, text="User-agent: *\nAllow: /")
        t = FakeLive(robots, Response(429, headers={"retry-after": "5"}),
                     Response(503), Response(503))
        a = _run(a, transport_factory=_factory(t))
        assert a.status == S.RETRY_WAIT
        job = _job(a)
        assert job.status == E.JobStatus.RETRY and job.attempt == 1
        later = timezone.now() + timedelta(seconds=30)
        a = _run(a, transport_factory=_factory(t), now=later)
        a = _run(a, transport_factory=_factory(t), now=later + timedelta(seconds=30))
        assert a.status == S.FAILED and a.error_code == "RETRIES_EXHAUSTED"
        assert a.attempts.count() == 3

    def test_write_5xx_goes_to_reconcile_not_retry(self, mila, x_acc):
        _live(mila)
        a = _go(_propose(mila, "channel.post.create", {"text": "Neizvesno"}, channel=x_acc))
        a = _run(a, transport_factory=_factory(FakeLive(Response(503))))
        assert a.status == S.RUNNING
        assert _job(a).status == E.JobStatus.FAILED
        t = ReconcileTask.objects.get(action=a)
        assert t.status == E.ReconcileStatus.PENDING
        found = FakeLive(Response(200, json={"data": [{"id": "9", "text": "Neizvesno"}]}))
        executor.run_reconcile(timezone.now() + timedelta(minutes=1),
                               transport_factory=_factory(found))
        a.refresh_from_db()
        assert a.status == S.SUCCEEDED and a.error_code == "RECONCILE_EFFECT_PRESENT"

    def test_reconcile_no_effect_allows_one_retry(self, mila, x_acc):
        _live(mila)
        a = _go(_propose(mila, "channel.post.create", {"text": "Nije stiglo"}, channel=x_acc))
        a = _run(a, transport_factory=_factory(FakeLive(TransportError("TIMEOUT"))))
        assert a.status == S.RUNNING
        executor.run_reconcile(timezone.now() + timedelta(minutes=1),
                               transport_factory=_factory(FakeLive(
                                   Response(200, json={"data": []}))))
        a.refresh_from_db()
        assert a.status == S.RETRY_WAIT and _job(a).status == E.JobStatus.RETRY

    def test_reconcile_unresolved_goes_to_human(self, mila, mail_ready):
        _live(mila)
        a = _go(_propose(mila, "mail.send", {"text": "x", "to": "a@b.test"},
                         channel=mail_ready))
        a = _run(a, transport_factory=_factory(FakeLive(TransportError("NETWORK"))))
        t = ReconcileTask.objects.get(action=a)
        for i in range(E.RECONCILE_MAX_CHECKS):
            executor.run_reconcile(timezone.now() + timedelta(hours=i + 1))
        t.refresh_from_db()
        a.refresh_from_db()
        assert t.status == E.ReconcileStatus.UNRESOLVED
        assert a.status == S.FAILED and a.error_code == "RECONCILE_UNRESOLVED"
        assert PolicyIncident.objects.filter(incident_kind="reconcile_unresolved").exists()

    def test_robots_disallow(self, mila):
        _live(mila)
        a = _go(_propose(mila, "browser.page.read", _read(4)))
        t = FakeLive(Response(200, text="User-agent: *\nDisallow: /"))
        a = _run(a, transport_factory=_factory(t))
        assert a.status == S.BLOCKED and a.error_code == "ROBOTS_DISALLOWED"
        assert len(t.sent) == 1  # samo robots.txt, stranica nije ni tražena
        ua = t.sent[0].headers["User-Agent"]
        assert ua.startswith("MercatoMasterBot/1.0") and "Chrome" not in ua

    def test_conditional_get_and_title(self, mila):
        _live(mila)
        a = _go(_propose(mila, "browser.page.read", _read(5)))
        page_resp = Response(200, text="<html><title>Vesti</title></html>",
                             headers={"etag": '"abc"'})
        a = _run(a, transport_factory=_factory(FakeLive(Response(404), page_resp)))
        assert a.status == S.SUCCEEDED and a.result_json["title"] == "Vesti"
        cache.delete("web:pace:example.com")
        b = _go(_propose(mila, "browser.page.read", {**_read(5), "note": "ponovo"}))
        t = FakeLive(Response(304))
        b = _run(b, transport_factory=_factory(t))
        assert t.sent[0].headers["If-None-Match"] == '"abc"'
        assert b.result_json["status"] == 304

    def test_breaker_opens_after_five_failures(self, mila):
        _live(mila)
        now = timezone.now()
        acc = _account(mila, E.ChannelType.X, E.IdentityVehicle.PROFILE, {},
                       handle="brk")
        with bind(actor_id="service:runtime"):
            from django.db import transaction

            with transaction.atomic():
                for i in range(E.BREAKER_FAILURES):
                    breaker.record("x", acc, ok=False, now=now + timedelta(seconds=i),
                                   persona=mila)
                assert breaker.allow("x", acc, now + timedelta(seconds=10))[0] is False
                assert breaker.allow("x", acc, now + timedelta(seconds=130))[0] is True
                breaker.record("x", acc, ok=True, now=now + timedelta(seconds=131))
        assert CircuitBreaker.objects.get(account=acc).state == E.BreakerState.CLOSED
        assert PolicyIncident.objects.filter(incident_kind="circuit_breaker",
                                             severity=E.IncidentSeverity.SEV3).exists()


# ---------------------------------------------------------------- kill-switch u letu


class TestKillSwitchInFlight:
    def test_stop_before_first_request_is_safe(self, mila, page):
        a = _go(_propose(mila, "channel.post.create", {"text": "Stop pre slanja"},
                         channel=page))

        def factory(dry):
            with bind(actor_id="user:ts"):
                service.activate_kill_switch(E.KillSwitchScope.PERSONA, "P-00001",
                                             reason="drill", actor="user:ts")
            return DryRunTransport()

        a = _run(a, transport_factory=factory)
        att = a.attempts.get()
        assert att.outcome == OC.ABORTED_SAFE and att.reason_code == "KILL_SWITCH"
        assert att.payload["requests"] == []
        assert a.status == S.BLOCKED and a.error_code == "KILL_SWITCH"
        assert RuntimeSession.objects.get().status == E.SessionStatus.ABORTED

    def test_stop_between_writes_is_unknown_effect(self, mila, ig, settings):
        settings.GLOBAL_EXTERNAL_ACTIONS_ENABLED = True
        _live(mila)
        a = _go(_propose(mila, "channel.post.create",
                         {"text": "Dva koraka", "image_url": "https://cdn.test/2.jpg"},
                         channel=ig))

        def first(req):
            with bind(actor_id="user:ts"):
                service.activate_kill_switch(E.KillSwitchScope.GLOBAL, "", reason="drill",
                                             actor="user:ts")
            return Response(200, json={"id": "container-1"})

        t = FakeLive(first)
        a = _run(a, transport_factory=_factory(t))
        assert len(t.sent) == 1  # media_publish nije poslat
        assert a.attempts.get().outcome == OC.UNKNOWN_EFFECT
        assert ReconcileTask.objects.filter(action=a).exists()

    def test_queued_jobs_dropped_after_kill_switch(self, mila):
        a = _go(_propose(mila, "browser.page.read", _read(6)))
        with bind(actor_id="user:ts"):
            service.activate_kill_switch(E.KillSwitchScope.GLOBAL, "", reason="drill",
                                         actor="user:ts")
        job = executor.execute_job(_job(a).pk)
        assert job.status == E.JobStatus.FAILED
        assert Action.objects.get(pk=a.pk).status == S.BLOCKED
        assert KillSwitch.objects.filter(is_active=True).count() == 1


# ---------------------------------------------------------------- sesije i lease


class TestSessionsAndLeases:
    def test_one_write_session_per_persona(self, mila, sandbox):
        a = _go(_propose(mila, "channel.post.create", {"text": "Prva"}, channel=sandbox))
        RuntimeSession.objects.create(persona=mila, session_type=E.SessionType.TOOL,
                                      is_write=True, status=E.SessionStatus.OPEN,
                                      started_at=timezone.now(),
                                      lease_expires_at=timezone.now() + timedelta(seconds=90))
        job = executor.execute_job(_job(a).pk)
        assert job.status == E.JobStatus.PENDING and job.last_error == "PERSONA_SESSION_BUSY"
        assert Action.objects.get(pk=a.pk).status == S.QUEUED

    def test_three_read_sessions_max(self, mila):
        now = timezone.now()
        for _ in range(3):
            RuntimeSession.objects.create(persona=mila, session_type=E.SessionType.BROWSER,
                                          is_write=False, status=E.SessionStatus.OPEN,
                                          started_at=now,
                                          lease_expires_at=now + timedelta(seconds=90))
        a = _go(_propose(mila, "browser.page.read", _read(7)))
        assert executor.execute_job(_job(a).pk).last_error == "PERSONA_SESSION_BUSY"

    def _stuck(self, mila, action_type, payload, **kw):
        a = _go(_propose(mila, action_type, payload, **kw))
        job = _job(a)
        now = timezone.now()
        s = RuntimeSession.objects.create(persona=mila, session_type=E.SessionType.TOOL,
                                          is_write=action_type != "browser.page.read",
                                          status=E.SessionStatus.OPEN, started_at=now,
                                          lease_expires_at=now - timedelta(seconds=1))
        WorkerJob.objects.filter(pk=job.pk).update(status=E.JobStatus.RUNNING, attempt=1,
                                                   session=s)
        Action.objects.filter(pk=a.pk).update(status=S.RUNNING, started_at=now)
        a.attempts.create(attempt_number=1, started_at=now, payload={"dry_run": True})
        return a

    def test_lost_read_is_retried(self, mila):
        a = self._stuck(mila, "browser.page.read", _read(8))
        assert executor.reap_leases() == 1
        a.refresh_from_db()
        assert a.status == S.RETRY_WAIT
        assert a.attempts.get().outcome == OC.ABORTED_SAFE

    def test_lost_write_goes_to_reconcile(self, mila, sandbox):
        a = self._stuck(mila, "channel.post.create", {"text": "Izgubljen"}, channel=sandbox)
        with bind(actor_id="user:op"):
            pass
        executor.reap_leases()
        a.refresh_from_db()
        assert a.status == S.RUNNING
        assert a.attempts.get().outcome == OC.UNKNOWN_EFFECT
        assert RuntimeSession.objects.get().status == E.SessionStatus.EXPIRED
        assert ReconcileTask.objects.filter(action=a).exists()


# ---------------------------------------------------------------- web forme


class TestForms:
    def test_form_only_on_allowed_domains(self, mila):
        with bind(actor_id="user:ts"):
            service.change_trust(mila, "browser.form_submit_approved", E.TrustLevel.L2,
                                 actor="user:ts", reason="QA")
        a = _go(_propose(mila, "browser.form.submit",
                         {"url": "https://tudji-sajt.rs/kontakt", "fields": {"poruka": "x"}}))
        a = _run(a)
        assert a.status == S.BLOCKED and a.error_code == "DOMAIN_NOT_ALLOWED"


# ---------------------------------------------------------------- API


class TestApi:
    @pytest.fixture
    def client(self, mila):
        from django.contrib.auth.models import Group, User

        u = User.objects.create_user("ops", password="x")
        u.groups.add(Group.objects.get(name=E.Role.SYSTEM_ADMIN.value))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}",
                      HTTP_X_ACTOR_ID="user:ops", HTTP_X_REQUEST_ID="test-f6-0001",
                      HTTP_TRACEPARENT="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
        return c

    def test_account_capabilities(self, client, page):
        r = client.get(f"/api/v1/channels/accounts/{page.id}/capabilities")
        assert r.status_code == 200
        rows = {x["action_type"]: x for x in r.json()["data"]["actions"]}
        assert rows["channel.read.public"]["available"] is False
        assert rows["channel.post.create"]["enabled_on_account"] is True
        assert r.json()["data"]["account"]["has_credential_ref"] is True
        assert "credential_ref" not in r.json()["data"]["account"]

    def test_ops_overview(self, client, mila):
        _go(_propose(mila, "browser.page.read", _read(9)))
        d = client.get("/api/v1/ops/overview").json()["data"]
        assert d["runtime"]["external_actions_enabled"] is False
        assert d["runtime"]["jobs"][E.JobStatus.PENDING.value] == 1

    def test_action_detail_shows_planned_requests(self, client, mila, sandbox, page):
        ChannelAccount.objects.filter(pk=page.pk).update(provider_account_id="777")
        a = _run(_go(_propose(mila, "channel.post.create", {"text": "Pregled"},
                              channel=page)))
        d = client.get(f"/api/v1/actions/{a.public_id}").json()["data"]
        assert d["attempts"][0]["dry_run"] is True
        assert d["attempts"][0]["requests"][0]["url"].endswith("/rest/posts")

    def test_manual_suppression(self, client):
        r = client.post("/api/v1/mail/suppressions", {"address": "neko@primer.rs"},
                        format="json", HTTP_IDEMPOTENCY_KEY="supp-0000001")
        assert r.status_code == 201, r.content
        assert suppression.is_suppressed("neko@primer.rs")


class TestLiveTransportSecrets:
    def test_secret_only_on_the_wire(self, settings, monkeypatch):
        settings.GLOBAL_EXTERNAL_ACTIONS_ENABLED = True
        monkeypatch.setenv("TOK_F6", "s3cr3t-value")
        seen = {}

        class _Resp:
            status = 200
            headers = {"Content-Type": "application/json"}

            def read(self):
                return b'{"id": "1"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(r, timeout):
            seen["auth"] = r.get_header("Authorization")
            return _Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        req = Request("POST", "https://api.x.com/2/tweets", json={"text": "x"}, auth="bearer")
        resp = LiveTransport().send(req, credential_ref="env:TOK_F6")
        assert resp.status == 200 and seen["auth"] == "Bearer s3cr3t-value"
        assert "s3cr3t-value" not in json.dumps(req.redacted())

    def test_missing_secret_is_needs_auth(self, settings):
        settings.GLOBAL_EXTERNAL_ACTIONS_ENABLED = True
        from apps.runtime.transport import CredentialMissing

        with pytest.raises(CredentialMissing):
            LiveTransport().send(Request("POST", "https://api.x.com/2/tweets", auth="bearer"),
                                 credential_ref="vault:nesto")
