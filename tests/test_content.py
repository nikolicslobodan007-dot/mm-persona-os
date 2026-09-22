"""F7 — Sadržaj i LLM Gateway. ADR-0009.

Invarijante:
  - nacrt je unutrašnji; objava ide SAMO kroz propose → policy → odobrenje;
  - AI oznaka je u tekstu kad persona traži ALWAYS_VISIBLE;
  - nacrt sa tvrdom zabranom ili ponovljen tekst ne može do objave;
  - sadržaj ne menja status sam — prati akciju;
  - spoljni model samo uz izričito uključivanje, samo provajder koji ne trenira
    na našim podacima, i u bazi ostaju samo hash-ovi prompta.
"""

from __future__ import annotations

import io
import json
from datetime import timedelta

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.context import bind
from apps.channels.models import ChannelAccount
from apps.content import service as content
from apps.content.models import ContentItem, Publication
from apps.llm_gateway import gateway, local
from apps.llm_gateway.models import LLMRoute, PromptRecord
from apps.observability.models import CostLedger
from apps.orchestration.models import Action, AgentRun
from apps.personas.models import Persona
from apps.policy import service as policy
from apps.runtime import executor
from apps.runtime.models import WorkerJob
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
CS = E.ContentStatus


@pytest.fixture
def sandbox(mila):
    call_command("pilot_setup", persona="P-00001", actor="user:slobodan", stdout=io.StringIO())
    return ChannelAccount.objects.get(persona=mila, channel_type=E.ChannelType.SANDBOX)


def _mila():
    return Persona.objects.get(public_id="P-00001")


def _draft(**kw):
    with bind(actor_id="user:op"):
        return content.draft(_mila(), **kw)


def _approve(item, decision=E.ApprovalStatus.APPROVED, **kw):
    pub = item.publications.get()
    with bind(actor_id="user:op"):
        policy.decide_approval(pub.action.approvals.get(), decision, actor="user:op",
                               role=E.Role.OPERATOR, reason="QA", **kw)
    content.sync_from_action(Action.objects.get(pk=pub.action_id))
    item.refresh_from_db()
    return item


# ---------------------------------------------------------------- lokalni šablon


class TestLocal:
    def test_deterministic_and_topic_sensitive(self):
        b = {"topic": "AI u prodaji", "facts": ["Brojka sa izvorom pomera odluku"]}
        a1 = local.compose(E.LLMPurpose.CONTENT_DRAFT, b, "")
        assert a1 == local.compose(E.LLMPurpose.CONTENT_DRAFT, b, "")
        assert "AI u prodaji" in a1 and "Brojka sa izvorom" in a1
        assert a1 != local.compose(E.LLMPurpose.CONTENT_DRAFT, {"topic": "B2B"}, "")

    def test_never_claims_to_be_human(self):
        from apps.policy import guards

        for t in ("AI", "B2B", "Prodaja", "posao", "tim"):
            text = local.compose(E.LLMPurpose.CONTENT_DRAFT, {"topic": t}, "")
            assert not guards.prohibitions("channel.post.create", {"text": text}, "")


# ---------------------------------------------------------------- gateway


class TestGateway:
    def test_local_by_default_and_no_prompt_text_stored(self, mila, settings):
        settings.LLM_EXTERNAL_ENABLED = False
        LLMRoute.objects.create(purpose=E.LLMPurpose.CONTENT_DRAFT, name="Claude",
                                provider="anthropic", model_key="claude-test", priority=1,
                                data_training_allowed=True)
        with bind(actor_id="user:op"):
            g = gateway.generate(E.LLMPurpose.CONTENT_DRAFT, "sys", "TAJNI-PROMPT-123",
                                 persona=mila, brief={"topic": "AI"})
        assert g.provider == "local" and g.amount_eur_cents == 0
        assert g.fallbacks == ["anthropic/claude-test:LLM_EXTERNAL_DISABLED"]
        rec = PromptRecord.objects.get(pk=g.record.pk)
        assert "TAJNI" not in json.dumps({k: str(v) for k, v in rec.__dict__.items()})
        assert len(rec.prompt_hash) == 64
        assert not CostLedger.objects.exists()

    def test_provider_that_may_train_is_skipped(self, mila, settings, monkeypatch):
        settings.LLM_EXTERNAL_ENABLED = True
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        LLMRoute.objects.create(purpose=E.LLMPurpose.CONTENT_DRAFT, name="X",
                                provider="anthropic", model_key="m", priority=1,
                                data_training_allowed=False)
        with bind(actor_id="user:op"):
            g = gateway.generate(E.LLMPurpose.CONTENT_DRAFT, "s", "p", persona=mila,
                                 brief={"topic": "AI"})
        assert g.provider == "local" and g.fallbacks[0].endswith("PROVIDER_MAY_TRAIN")

    def test_external_call_and_cost(self, mila, settings, monkeypatch):
        settings.LLM_EXTERNAL_ENABLED = True
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        LLMRoute.objects.create(purpose=E.LLMPurpose.CONTENT_DRAFT, name="Claude",
                                provider="anthropic", model_key="claude-test", priority=1,
                                data_training_allowed=True,
                                input_price_micro_eur_per_1k=3_000,
                                output_price_micro_eur_per_1k=15_000)
        seen = {}

        def fake(url, headers, body, timeout):
            seen.update(url=url, key=headers["x-api-key"], model=body["model"])
            return {"content": [{"type": "text", "text": "Tekst iz modela."}],
                    "usage": {"input_tokens": 1000, "output_tokens": 200},
                    "stop_reason": "end_turn"}

        monkeypatch.setattr(gateway, "_post_json", fake)
        with bind(actor_id="user:op"):
            g = gateway.generate(E.LLMPurpose.CONTENT_DRAFT, "s", "p", persona=mila)
        assert g.text == "Tekst iz modela." and g.provider == "anthropic"
        assert seen == {"url": "https://api.anthropic.com/v1/messages", "key": "sk-test",
                        "model": "claude-test"}
        # 1000×3 + 200×15 = 6000 mikroevra po 1k → 0,6 centa → 1 cent naviše
        assert g.amount_eur_cents == 1
        assert CostLedger.objects.get().cost_bucket == E.CostBucket.LLM

    def _keyed(self, mila, settings, monkeypatch):
        settings.LLM_EXTERNAL_ENABLED = True
        LLMRoute.objects.create(purpose=E.LLMPurpose.CONTENT_DRAFT, name="C",
                                provider="anthropic", model_key="m", priority=1,
                                data_training_allowed=True)
        seen = []

        def fake(url, headers, body, timeout):
            seen.append(headers["x-api-key"])
            return {"content": [{"type": "text", "text": "Iz modela."}],
                    "usage": {"input_tokens": 10, "output_tokens": 5}, "stop_reason": "end_turn"}

        monkeypatch.setattr(gateway, "_post_json", fake)
        return seen

    def test_persona_key_wins_over_shared(self, mila, settings, monkeypatch):
        """ADR-0013 — svaka persona svoj ključ."""
        seen = self._keyed(mila, settings, monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "zajednicki")
        monkeypatch.setenv("ANTHROPIC_API_KEY_P00001", "  milin  ")
        with bind(actor_id="user:op"):
            gateway.generate(E.LLMPurpose.CONTENT_DRAFT, "s", "p", persona=mila)
            gateway.generate(E.LLMPurpose.CONTENT_DRAFT, "s", "p")
        assert seen == ["milin", "zajednicki"]
        assert gateway.credential_ref("anthropic", mila) == (
            "env:ANTHROPIC_API_KEY_P00001", "persona")

    def test_shared_key_when_persona_has_none(self, mila, settings, monkeypatch):
        seen = self._keyed(mila, settings, monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "zajednicki")
        monkeypatch.delenv("ANTHROPIC_API_KEY_P00001", raising=False)
        with bind(actor_id="user:op"):
            gateway.generate(E.LLMPurpose.CONTENT_DRAFT, "s", "p", persona=mila)
        assert seen == ["zajednicki"]

    def test_require_persona_key_falls_back_to_template(self, mila, settings, monkeypatch):
        seen = self._keyed(mila, settings, monkeypatch)
        settings.LLM_REQUIRE_PERSONA_KEY = True
        monkeypatch.setenv("ANTHROPIC_API_KEY", "zajednicki")
        monkeypatch.delenv("ANTHROPIC_API_KEY_P00001", raising=False)
        with bind(actor_id="user:op"):
            g = gateway.generate(E.LLMPurpose.CONTENT_DRAFT, "s", "p", persona=mila,
                                 brief={"topic": "AI"})
        assert seen == [] and g.provider == "local"
        assert g.fallbacks == ["anthropic/m:NO_PERSONA_KEY"]

    def test_external_failure_falls_back_to_local(self, mila, settings, monkeypatch):
        settings.LLM_EXTERNAL_ENABLED = True
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        LLMRoute.objects.create(purpose=E.LLMPurpose.CONTENT_DRAFT, name="C",
                                provider="anthropic", model_key="m", priority=1,
                                data_training_allowed=True)

        def boom(*a, **k):
            raise gateway.LLMError("HTTP_529", "overloaded")

        monkeypatch.setattr(gateway, "_post_json", boom)
        with bind(actor_id="user:op"):
            g = gateway.generate(E.LLMPurpose.CONTENT_DRAFT, "s", "p", persona=mila,
                                 brief={"topic": "AI"})
        assert g.provider == "local" and g.fallbacks == ["anthropic/m:HTTP_529"]
        assert PromptRecord.objects.filter(error_code="HTTP_529").exists()


# ---------------------------------------------------------------- nacrt


class TestDraft:
    def test_generated_draft_with_disclosure_and_run(self, mila):
        item = _draft(topic="AI u B2B prodaji")
        assert item.status == CS.DRAFT and item.provenance == E.Provenance.GENERATED
        assert item.body.endswith("— Mila Vuković · AI persona")
        assert item.disclosure_included is True
        assert item.run.reason_code == E.DecisionReason.OPERATOR_TASK
        assert item.citations and item.content_hash
        assert PromptRecord.objects.filter(run=item.run).exists()

    def test_internal_memories_never_leak_into_text(self, mila):
        from apps.memory.models import MemoryItem

        item = _draft(topic="Prodaja")
        cited = MemoryItem.objects.filter(id__in=[c["memory_id"] for c in item.citations])
        assert all(m.memory_type in ("semantic", "content") for m in cited)
        for m in MemoryItem.objects.filter(persona=mila).exclude(
                memory_type__in=["semantic", "content"]):
            assert m.content.rstrip(".") not in item.body
        assert "Pre svake objave" not in item.body

    def test_prohibited_text_is_rejected(self, mila):
        item = _draft(body="Ja sam prava osoba, ne AI.")
        assert item.status == CS.REJECTED
        assert item.status_reason == "HARD_PROHIBITION:IDENTITY_IMPERSONATION"

    def test_repetition_is_rejected(self, mila):
        text = "Kupci u B2B prodaji veruju brojkama sa izvorom, ne pridevima i obećanjima."
        assert _draft(body=text).status == CS.DRAFT
        again = _draft(body="  " + text)
        assert again.status == CS.REJECTED and again.status_reason == "REPETITION"

    def test_idea_dedupe(self, mila):
        a, c1 = content.create_idea(mila, "AI u prodaji!")
        b, c2 = content.create_idea(mila, "ai u prodaji")
        assert c1 and not c2 and a.pk == b.pk


# ---------------------------------------------------------------- objava


class TestPublish:
    def test_full_loop_on_sandbox(self, mila, sandbox):
        item = _draft(topic="Brojke u prodaji")
        with bind(actor_id="user:op"):
            pr = content.submit(item, sandbox)
        item.refresh_from_db()
        assert pr.action.status == E.ActionStatus.APPROVAL_PENDING
        assert pr.approval.approval_class == E.ApprovalClass.A2
        assert item.status == CS.IN_REVIEW
        assert not WorkerJob.objects.filter(action=pr.action).exists()

        item = _approve(item)
        assert item.status == CS.APPROVED
        executor.execute_job(WorkerJob.objects.get(action=pr.action).pk)
        content.sync_from_action(Action.objects.get(pk=pr.action.pk))
        item.refresh_from_db()
        pub = item.publications.get()
        assert item.status == CS.PUBLISHED and pub.status == E.PublicationStatus.PUBLISHED
        assert pub.provider_post_id.startswith("sandbox:")
        assert pub.provider_payload["dry_run"] is True

    def test_rejected_by_human(self, mila, sandbox):
        item = _draft(topic="Odbijena tema")
        with bind(actor_id="user:op"):
            content.submit(item, sandbox)
        item = _approve(item, E.ApprovalStatus.REJECTED)
        assert item.status == CS.REJECTED and item.status_reason == "APPROVAL_REJECTED"
        assert item.publications.get().status == E.PublicationStatus.FAILED

    def test_approved_with_changes_updates_content(self, mila, sandbox):
        item = _draft(topic="Izmena teksta")
        with bind(actor_id="user:op"):
            content.submit(item, sandbox)
        new_text = "Kraća verzija objave.\n\n— Mila Vuković · AI persona"
        item = _approve(item, E.ApprovalStatus.APPROVED_WITH_CHANGES,
                        payload_override={"text": new_text, "content_id": str(item.id)})
        assert item.body == new_text and item.version == 2 and item.status == CS.APPROVED

    def test_consumer_keeps_content_in_sync(self, mila, sandbox,
                                            django_capture_on_commit_callbacks):
        item = _draft(topic="Sinhronizacija")
        with bind(actor_id="user:op"):
            content.submit(item, sandbox)
        ap = item.publications.get().action.approvals.get()
        with django_capture_on_commit_callbacks(execute=True):
            with bind(actor_id="user:op"):
                policy.decide_approval(ap, E.ApprovalStatus.APPROVED, actor="user:op",
                                       role=E.Role.OPERATOR)
        item.refresh_from_db()
        assert item.status == CS.APPROVED

    def test_schedule_window_is_bounded_by_approval_ttl(self, mila, sandbox):
        item = _draft(topic="Kasnije")
        with pytest.raises(content.ContentError), bind(actor_id="user:op"):
            content.submit(item, sandbox, scheduled_for=timezone.now() + timedelta(days=2))
        with bind(actor_id="user:op"):
            content.submit(item, sandbox, scheduled_for=timezone.now() + timedelta(minutes=30))
        assert Action.objects.get(publications__content=item).scheduled_for is not None

    def test_rejected_draft_cannot_be_submitted(self, mila, sandbox):
        item = _draft(body="Moj JMBG je 0101990710012")
        with pytest.raises(content.ContentError), bind(actor_id="user:op"):
            content.submit(item, sandbox)
        assert not Publication.objects.exists()


# ---------------------------------------------------------------- planer


class TestPlanner:
    def _run(self, mila):
        now = timezone.now()
        import uuid

        from common import ids as I

        return AgentRun.objects.create(
            public_id=I.ulid_public_id(I.EntityKind.AGENT_RUN, now), persona=mila,
            wake_priority=E.WakePriority.ROUTINE_WINDOW, status=E.RunStatus.COMPLETED,
            started_at=now, ended_at=now, trace_id=uuid.uuid4(),
            decision=E.WakeDecision.ACT, reason_code=E.DecisionReason.ROUTINE_WINDOW_DUE)

    def test_no_channel_means_draft_only(self, mila):
        run = self._run(mila)
        with bind(actor_id="service:planner"):
            item = content.plan_post_for_run(run)
        assert item.status == CS.DRAFT and not item.publications.exists()
        assert item.title in ("AI", "B2B", "Prodaja")

    def test_with_sandbox_goes_to_approval_and_is_idempotent(self, mila, sandbox):
        run = self._run(mila)
        with bind(actor_id="service:planner"):
            item = content.plan_post_for_run(run)
            assert content.plan_post_for_run(run).pk == item.pk
        assert item.status == CS.IN_REVIEW
        assert item.publications.get().channel_account == sandbox
        assert ContentItem.objects.filter(run=run).count() == 1

    def test_simulation_never_picks_a_real_channel(self, mila, sandbox):
        from tests.test_runtime import _account

        _account(mila, E.ChannelType.X, E.IdentityVehicle.PROFILE,
                 {"content.publish_approved": E.TrustLevel.L1}, provider_account_id="1")
        assert content.publish_channel(_mila()).channel_type == E.ChannelType.SANDBOX

    def test_suspended_persona_does_not_draft(self, mila):
        Persona.objects.filter(pk=mila.pk).update(status=E.PersonaStatus.SUSPENDED)
        run = self._run(_mila())
        assert content.plan_post_for_run(run) is None


class TestPilotSetup:
    def test_requires_human_actor(self, mila):
        with pytest.raises(CommandError):
            call_command("pilot_setup", persona="P-00001", actor="service:x",
                         stdout=io.StringIO())

    def test_idempotent(self, mila):
        out = io.StringIO()
        call_command("pilot_setup", persona="P-00001", actor="user:slobodan", stdout=out)
        call_command("pilot_setup", persona="P-00001", actor="user:slobodan", stdout=out)
        assert "već uključen" in out.getvalue()
        assert policy.trust_map(_mila())["content.publish_approved"] == E.TrustLevel.L1


# ---------------------------------------------------------------- API


class TestApi:
    @pytest.fixture
    def client(self, mila):
        from django.contrib.auth.models import Group, User

        u = User.objects.create_user("op7", password="x")
        u.groups.add(Group.objects.get(name=E.Role.OPERATOR.value))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}",
                      HTTP_X_ACTOR_ID="user:op7", HTTP_X_REQUEST_ID="test-f7-0001",
                      HTTP_TRACEPARENT="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
        return c

    def test_draft_schedule_and_approval_queue(self, client, sandbox):
        r = client.post("/api/v1/content/items", {"persona_id": "P-00001", "topic": "AI"},
                        format="json", HTTP_IDEMPOTENCY_KEY="content-0001")
        assert r.status_code == 201, r.content
        cid = r.json()["data"]["content_id"]
        r = client.post(f"/api/v1/content/items/{cid}/schedule",
                        {"channel_account_id": str(sandbox.id)}, format="json",
                        HTTP_IDEMPOTENCY_KEY="schedule-0001")
        assert r.status_code == 201, r.content
        d = r.json()["data"]
        assert d["approval_id"] and d["content"]["status"] == CS.IN_REVIEW
        q = client.get("/api/v1/approvals").json()["data"]
        mine = [a for a in q if a["approval_id"] == d["approval_id"]][0]
        assert mine["channel"]["channel_type"] == "SANDBOX"
        assert "AI persona" in mine["payload_preview"]["text"]
        got = client.get(f"/api/v1/content/items/{cid}").json()["data"]
        assert got["publications"][0]["action_id"] == d["action_id"]
        assert client.get("/api/v1/content/items?persona_id=P-00001").json()["data"]
