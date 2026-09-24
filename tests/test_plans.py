"""ADR-0021 — plan sa checkpointima.

  - koraci idu redom, izlaz prethodnog vidi sledeći;
  - korak koji čeka čoveka pauzira plan i stanje ostaje u bazi;
  - odobrenje nastavlja plan, odbijanje ga zaustavlja **sa razlogom**;
  - kvar koraka ne ruši sistem — plan se zatvara kao nedovršen;
  - odgovor na poštu je od sada plan od dva koraka.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from django.core.management import call_command

from api.context import bind
from apps.channels import mailbox, reply
from apps.orchestration import plans
from apps.orchestration.models import AgentPlan, PlanStep
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
PS, SS = E.PlanStatus, E.StepStatus
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)

HUMAN = (b"From: Petar Petrovic <petar@kupac.rs>\r\n"
         b"To: mila.vukovic@webkorporacija.com\r\nSubject: Upit za rokove\r\n"
         b"Message-ID: <p1@kupac.rs>\r\nDate: Thu, 24 Sep 2026 09:00:00 +0200\r\n"
         b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
         b"Postovani, koliki su rokovi isporuke?\r\n")


@pytest.fixture
def probni():
    """Tri obrađivača za probu: uspeh, čekanje i kvar."""
    seen = []

    @plans.handler("proba.ok")
    def _ok(step, state):
        seen.append((step.sequence, dict(state)))
        return plans.Done({"broj": step.input_json.get("broj", 0),
                           "video": sorted(state["steps"])})

    @plans.handler("proba.pukne")
    def _boom(step, state):
        raise RuntimeError("puklo je")

    return seen


class TestSequence:
    def test_steps_run_in_order_and_see_previous_output(self, mila, probni):
        with bind(actor_id="user:op"):
            plan = plans.start(mila, "Proba", [
                {"handler": "proba.ok", "description": "prvi", "input": {"broj": 1}},
                {"handler": "proba.ok", "description": "drugi", "input": {"broj": 2}},
            ], actor="user:op", now=NOW)
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        assert plan.status == PS.COMPLETED
        steps = list(plan.steps.order_by("sequence"))
        assert [s.status for s in steps] == [SS.DONE, SS.DONE]
        assert steps[1].output_json["video"] == ["1", "2"]     # vidi i svoj i prethodni

    def test_unknown_handler_is_refused_at_start(self, mila, probni):
        with bind(actor_id="user:op"), pytest.raises(plans.PlanError) as e:
            plans.start(mila, "Proba", [{"handler": "nema.ga"}], actor="user:op", now=NOW)
        assert e.value.code == "VALIDATION_ERROR"
        assert not AgentPlan.objects.exists()

    def test_broken_step_stops_plan_with_reason(self, mila, probni):
        with bind(actor_id="user:op"):
            plan = plans.start(mila, "Proba", [
                {"handler": "proba.pukne", "description": "puca"},
                {"handler": "proba.ok", "description": "ne stiže"},
            ], actor="user:op", now=NOW)
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        steps = list(plan.steps.order_by("sequence"))
        assert plan.status == PS.ABANDONED
        assert steps[0].status == SS.FAILED and "puklo je" in steps[0].output_json["reason"]
        assert steps[1].status == SS.PENDING          # drugi korak se nije ni pokrenuo

    def test_plan_is_capped(self, mila, probni):
        with bind(actor_id="user:op"), pytest.raises(plans.PlanError):
            plans.start(mila, "Predug", [{"handler": "proba.ok"}] * (plans.MAX_STEPS + 1),
                        actor="user:op", now=NOW)


class TestCheckpoint:
    """Plan koji čeka čoveka — glavni razlog zbog kog ovo postoji."""

    @pytest.fixture
    def cekanje(self, mila, page):
        from apps.content import service as content

        @plans.handler("proba.objavi")
        def _publish(step, state):
            item = content.draft(mila, topic="Rokovi u B2B")
            pr = content.submit(item, page)
            return (plans.Waiting(pr.action, note="čeka odobrenje")
                    if pr.action.status == E.ActionStatus.APPROVAL_PENDING
                    else plans.Done({"action": pr.action.public_id}))

        with bind(actor_id="user:op"):
            plan = plans.start(mila, "Objavi tekst", [
                {"handler": "proba.objavi", "description": "objava uz odobrenje"},
            ], actor="user:op", now=NOW)
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        return plan

    def test_plan_pauses_and_state_survives(self, cekanje):
        step = cekanje.steps.get(sequence=1)
        assert cekanje.status == PS.ACTIVE and step.status == SS.RUNNING
        assert step.output_json["waiting_for"].startswith("ACT-")
        # stanje je u bazi: novo čitanje vidi isto
        assert PlanStep.objects.get(pk=step.pk).output_json["waiting_for"]

    def test_approval_continues_the_plan(self, cekanje, django_capture_on_commit_callbacks):
        from apps.policy.models import ApprovalRequest

        ap = ApprovalRequest.objects.filter(status=E.ApprovalStatus.PENDING).latest("created_at")
        with bind(actor_id="user:boss"), django_capture_on_commit_callbacks(execute=True):
            policy.decide_approval(ap, E.ApprovalStatus.APPROVED, actor="user:boss",
                                   role=E.Role.OPERATOR, reason="može")
        cekanje.refresh_from_db()
        step = cekanje.steps.get(sequence=1)
        assert step.status == SS.DONE and step.output_json["decision"] == "approved"
        assert cekanje.status == PS.COMPLETED

    def test_rejection_stops_the_plan_with_reason(self, cekanje,
                                                  django_capture_on_commit_callbacks):
        from apps.policy.models import ApprovalRequest

        ap = ApprovalRequest.objects.filter(status=E.ApprovalStatus.PENDING).latest("created_at")
        with bind(actor_id="user:boss"), django_capture_on_commit_callbacks(execute=True):
            policy.decide_approval(ap, E.ApprovalStatus.REJECTED, actor="user:boss",
                                   role=E.Role.OPERATOR, reason="Previše obećava")
        cekanje.refresh_from_db()
        step = cekanje.steps.get(sequence=1)
        assert cekanje.status == PS.ABANDONED
        assert step.status == SS.FAILED
        assert step.output_json["decision"] == "rejected"
        assert "Previše obećava" in step.output_json["reason"]

    def test_decision_on_unrelated_action_changes_nothing(
            self, mila, page, django_capture_on_commit_callbacks):
        from apps.content import service as content
        from apps.policy.models import ApprovalRequest

        with bind(actor_id="user:op"):
            item = content.draft(mila, topic="Bez plana")
            content.submit(item, page)
            ap = ApprovalRequest.objects.filter(status=E.ApprovalStatus.PENDING).latest(
                "created_at")
        with bind(actor_id="user:boss"), django_capture_on_commit_callbacks(execute=True):
            policy.decide_approval(ap, E.ApprovalStatus.APPROVED, actor="user:boss",
                                   role=E.Role.OPERATOR, reason="ok")
        assert not AgentPlan.objects.exists()


class TestMailReplyAsPlan:
    @pytest.fixture
    def mc(self, mila, settings, monkeypatch):
        settings.MAILCOW_ENABLED = True
        settings.MAILCOW_URL = "https://mail.primer.rs"
        settings.AGENT_MAIL_DOMAIN = "webkorporacija.com"
        monkeypatch.setenv("MAILCOW_API_KEY", "kljuc")
        monkeypatch.setenv("MAILBOX_PASSWORD_SECRET", "tajna")
        monkeypatch.setattr(mailbox, "_api",
                            lambda path, body=None: [{"type": "success", "msg": ["ok"]}])
        with bind(actor_id="user:boss"):
            call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
            acc = mailbox.provision(mila, actor="user:boss")
            policy.change_trust(mila, mailbox.REPLY_CAPABILITY, E.TrustLevel.L2,
                                actor="user:ts", reason="QA")
            msg = mailbox.store_inbound(acc, HUMAN, NOW)
        return msg

    def test_reply_is_a_two_step_plan_waiting_for_approval(self, mc):
        with bind(actor_id="service:mail-poll"):
            action = reply.draft_reply(mc, now=NOW)
        assert action is not None and action.status == E.ActionStatus.APPROVAL_PENDING
        plan = AgentPlan.objects.get(persona=mc.persona)
        steps = list(plan.steps.order_by("sequence"))
        assert [s.status for s in steps] == [SS.DONE, SS.RUNNING]
        assert steps[0].output_json["text"].strip()
        assert steps[1].output_json["waiting_for"] == action.public_id
        assert plan.status == PS.ACTIVE

    def test_rejected_reply_leaves_a_written_reason(self, mc,
                                                    django_capture_on_commit_callbacks):
        from apps.policy.models import ApprovalRequest

        with bind(actor_id="service:mail-poll"):
            reply.draft_reply(mc, now=NOW)
        ap = ApprovalRequest.objects.filter(status=E.ApprovalStatus.PENDING).latest("created_at")
        with bind(actor_id="user:boss"), django_capture_on_commit_callbacks(execute=True):
            policy.decide_approval(ap, E.ApprovalStatus.REJECTED, actor="user:boss",
                                   role=E.Role.OPERATOR, reason="Ne obećavaj rok")
        plan = AgentPlan.objects.get(persona=mc.persona)
        assert plan.status == PS.ABANDONED
        assert "Ne obećavaj rok" in plan.steps.get(sequence=2).output_json["reason"]


class TestHandlerRegistry:
    """Obrađivač postoji tek kad se njegov modul uveze — motor to radi sam.

    Nalaz od 24.09.: `manage.py plan --handlers` na serveru je ispisao samo
    `org.delegate`, jer se `apps.channels.reply` uvozi tek kad stigne pošta.
    Isti plan bi tako radio u workeru, a padao u web procesu.
    """

    def test_engine_loads_every_handler_module(self):
        imena = plans.registered()
        for ime in ("mail.draft", "mail.send", "org.delegate"):
            assert ime in imena
