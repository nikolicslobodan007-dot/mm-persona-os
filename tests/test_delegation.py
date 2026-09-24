"""ADR-0022 — delegiranje po organizaciji.

  - posao ide samo nadole: šef svom neposrednom izvršiocu;
  - niko ne zadaje sam sebi, ni nagore, ni u drugi sektor;
  - delegiranje ne daje nikakvu dozvolu — izvršilac radi sa svojim poverenjem;
  - šefov korak čeka izvršiočev plan i nastavlja se kad ovaj završi;
  - kad izvršilac ne završi, šefov plan staje **sa razlogom**;
  - lanac delegiranja je ograničen po dubini.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from django.core.management import CommandError, call_command

from api.context import bind
from apps.orchestration import plans
from apps.orchestration.models import AgentPlan
from apps.personas import org
from apps.personas.models import Persona, Position
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
PS, SS = E.PlanStatus, E.StepStatus
NOW = datetime(2026, 9, 24, 11, 0, tzinfo=UTC)


@pytest.fixture
def ekipa(mila):
    """Mila je šef marketinga; Jovan je njen urednik; Ana je u podršci."""
    with bind(actor_id="user:slobodan"):
        call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
        org.assign(mila, Position.objects.get(code="SEF-MKT"), actor="user:slobodan")
        jovan = _person("P-00002", "Jovan")
        ana = _person("P-00003", "Ana")
        org.assign(jovan, Position.objects.get(code="URE-SR"), actor="user:slobodan")
        org.assign(ana, Position.objects.get(code="POD-SR"), actor="user:slobodan")
    return Persona.objects.get(pk=mila.pk), jovan, ana


def _person(pid: str, name: str) -> Persona:
    return Persona.objects.create(
        public_id=pid, slug=pid.lower(), display_name=f"{name} ({pid}) (AI)",
        persona_type=E.PersonaType.AI_CREATOR, status=E.PersonaStatus.READY,
        disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE, primary_locale="sr-Latn",
        timezone="Europe/Belgrade")


@pytest.fixture
def jovanov_kanal(ekipa):
    """Izvršilac ima svoj kanal i svoje poverenje — delegiranje mu ne daje ništa."""
    from apps.channels.models import ChannelAccount, ChannelCapability
    from apps.policy import service as policy

    _, jovan, _ = ekipa
    acc = ChannelAccount.objects.create(
        persona=jovan, channel_type=E.ChannelType.LINKEDIN, handle="jovan-page",
        identity_vehicle=E.IdentityVehicle.PAGE, status=E.AccountStatus.ACTIVE,
        disclosure_label_status=E.DisclosureLabelStatus.SET, credential_ref="vault:test",
        named_human_admin="Slobodan")
    ChannelCapability.objects.create(account=acc, capability="content.publish_approved",
                                     is_enabled=True, source="policy",
                                     evidence_level=E.EvidenceLevel.RESPONSE_ONLY)
    with bind(actor_id="user:ts"):
        policy.change_trust(jovan, "content.publish_approved", E.TrustLevel.L1,
                            actor="user:ts", reason="QA prolaz")
    return acc


@pytest.fixture
def poslovi():
    """Obrađivači za probu: jedan uspe, jedan čeka odluku, jedan padne."""

    @plans.handler("proba.uradi")
    def _ok(step, state):
        return plans.Done({"uradio": step.input_json.get("sta", "")})

    @plans.handler("proba.padne")
    def _bad(step, state):
        return plans.Failed("nema podataka")

    @plans.handler("proba.ceka")
    def _wait(step, state):
        from apps.content import service as content

        item = content.draft(step.plan.persona, topic="Rokovi")
        acc = step.plan.persona.channel_accounts.first()
        pr = content.submit(item, acc)
        return plans.Waiting(pr.action)


def _delegate(boss, worker, steps, *, goal="Zadatak"):
    return plans.start(boss, "Vodim posao", [
        {"handler": "org.delegate", "description": f"Zadaj: {worker.public_id}",
         "input": {"to": worker.public_id, "goal": goal, "steps": steps}},
        {"handler": "proba.uradi", "description": "Zaključi",
         "input": {"sta": "zaključeno"}},
    ], actor="user:op", now=NOW)


class TestPravila:
    def test_only_downwards(self, ekipa, poslovi):
        mila, jovan, ana = ekipa
        assert org.can_delegate(mila, jovan) == ""
        assert "ne odgovara" in org.can_delegate(jovan, mila)      # nagore ne
        assert "ne odgovara" in org.can_delegate(mila, ana)        # drugi sektor ne
        assert "sam sebi" in org.can_delegate(mila, mila)

    def test_archived_worker_is_refused(self, ekipa, poslovi):
        mila, jovan, _ = ekipa
        Persona.objects.filter(pk=jovan.pk).update(status=E.PersonaStatus.PAUSED.value)
        jovan.refresh_from_db()
        assert "PAUSED" in org.can_delegate(mila, jovan)

    def test_refused_delegation_stops_the_plan(self, ekipa, poslovi):
        mila, _, ana = ekipa
        with bind(actor_id="user:op"):
            plan = _delegate(mila, ana, [{"handler": "proba.uradi"}])
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        assert plan.status == PS.ABANDONED
        assert "ne odgovara" in plan.steps.get(sequence=1).output_json["reason"]
        assert AgentPlan.objects.count() == 1          # pod-plan nije ni nastao

    def test_delegation_gives_no_permission(self, ekipa, poslovi):
        """Izvršilac posle zadatka ima isto poverenje kao i pre njega."""
        mila, jovan, _ = ekipa
        before = jovan.trust_level
        with bind(actor_id="user:op"):
            plan = _delegate(mila, jovan, [{"handler": "proba.uradi",
                                            "input": {"sta": "napisano"}}])
            plans.advance(plan, now=NOW)
        jovan.refresh_from_db()
        assert jovan.trust_level == before == E.TrustLevel.L0


class TestPredaja:
    def test_child_finishes_and_parent_continues(self, ekipa, poslovi):
        mila, jovan, _ = ekipa
        with bind(actor_id="user:op"):
            plan = _delegate(mila, jovan, [{"handler": "proba.uradi",
                                            "input": {"sta": "napisano"}}])
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        child = AgentPlan.objects.get(persona=jovan)
        assert child.status == PS.COMPLETED
        assert plan.status == PS.COMPLETED
        assert plan.steps.get(sequence=1).output_json["waiting_for_plan"] == child.public_id
        assert plan.steps.get(sequence=2).status == SS.DONE

    def test_child_that_waits_pauses_the_parent(self, ekipa, poslovi, jovanov_kanal):
        """Izvršilac čeka odobrenje → i šefov plan stoji dok odluka ne padne."""
        mila, jovan, _ = ekipa
        with bind(actor_id="user:op"):
            plan = _delegate(mila, jovan, [{"handler": "proba.ceka"}])
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        child = AgentPlan.objects.get(persona=jovan)
        assert child.status == PS.ACTIVE and child.steps.get(sequence=1).status == SS.RUNNING
        assert plan.status == PS.ACTIVE
        assert plan.steps.get(sequence=1).status == SS.RUNNING
        assert plan.steps.get(sequence=2).status == SS.PENDING

    def test_approval_on_the_child_finishes_the_whole_chain(
            self, ekipa, poslovi, jovanov_kanal, django_capture_on_commit_callbacks):
        """Jedna odluka čoveka nastavlja i izvršioca i nalogodavca."""
        from apps.policy import service as policy
        from apps.policy.models import ApprovalRequest

        mila, jovan, _ = ekipa
        with bind(actor_id="user:op"):
            plan = _delegate(mila, jovan, [{"handler": "proba.ceka"}])
            plans.advance(plan, now=NOW)
        ap = ApprovalRequest.objects.filter(status=E.ApprovalStatus.PENDING).latest("created_at")
        with bind(actor_id="user:boss"), django_capture_on_commit_callbacks(execute=True):
            policy.decide_approval(ap, E.ApprovalStatus.APPROVED, actor="user:boss",
                                   role=E.Role.OPERATOR, reason="može")
        plan.refresh_from_db()
        assert AgentPlan.objects.get(persona=jovan).status == PS.COMPLETED
        assert plan.status == PS.COMPLETED
        assert plan.steps.get(sequence=2).status == SS.DONE

    def test_child_failure_stops_the_parent_with_reason(self, ekipa, poslovi):
        mila, jovan, _ = ekipa
        with bind(actor_id="user:op"):
            plan = _delegate(mila, jovan, [{"handler": "proba.padne"}])
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        child = AgentPlan.objects.get(persona=jovan)
        assert child.status == PS.ABANDONED
        assert plan.status == PS.ABANDONED
        assert "nema podataka" in plan.steps.get(sequence=1).output_json["reason"]
        assert plan.steps.get(sequence=2).status == SS.PENDING


class TestDubina:
    @pytest.fixture
    def lanac(self, ekipa):
        """Mila → Jovan → Marko → Nina: četiri nivoa, jedan preko dozvoljenog."""
        mila, jovan, _ = ekipa
        dep = org.department_of(jovan)
        with bind(actor_id="user:slobodan"):
            marko = _person("P-00004", "Marko")
            p_marko = Position.objects.create(
                department=dep, code="URE-ML", title="Mlađi urednik",
                level=E.OrgLevel.JUNIOR.value,
                reports_to=Position.objects.get(code="URE-SR"))
            org.assign(marko, p_marko, actor="user:slobodan")
            nina = _person("P-00005", "Nina")
            org.assign(nina, Position.objects.create(
                department=dep, code="URE-PR", title="Pripravnik",
                level=E.OrgLevel.JUNIOR.value, reports_to=p_marko),
                actor="user:slobodan")
        return mila, jovan, marko, nina

    def test_two_levels_are_allowed(self, lanac, poslovi):
        mila, jovan, marko, _ = lanac
        deeper = [{"handler": "org.delegate", "description": "dalje nadole",
                   "input": {"to": marko.public_id, "goal": "drugi nivo",
                             "steps": [{"handler": "proba.uradi"}]}}]
        with bind(actor_id="user:op"):
            plan = _delegate(mila, jovan, deeper)
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        assert plan.status == PS.COMPLETED
        assert AgentPlan.objects.get(persona=marko).status == PS.COMPLETED

    def test_third_level_is_refused_and_failure_travels_up(self, lanac, poslovi):
        mila, jovan, marko, nina = lanac
        najdublje = [{"handler": "org.delegate", "description": "treći nivo",
                      "input": {"to": nina.public_id, "goal": "predubok lanac",
                                "steps": [{"handler": "proba.uradi"}]}}]
        deeper = [{"handler": "org.delegate", "description": "drugi nivo",
                   "input": {"to": marko.public_id, "goal": "drugi nivo",
                             "steps": najdublje}}]
        with bind(actor_id="user:op"):
            plan = _delegate(mila, jovan, deeper)
            plans.advance(plan, now=NOW)
        plan.refresh_from_db()
        assert not AgentPlan.objects.filter(persona=nina).exists()
        assert AgentPlan.objects.get(persona=marko).status == PS.ABANDONED
        assert plan.status == PS.ABANDONED
        assert "dublji" in plan.steps.get(sequence=1).output_json["reason"]


class TestPosao:
    """ADR-0024 — izvršilac dobija pravi posao, ne prazan plan."""

    def test_boss_orders_a_draft_and_gets_it_back(self, ekipa):
        mila, jovan, _ = ekipa
        out = io.StringIO()
        with bind(actor_id="user:slobodan"):
            call_command("plan", "--persona", "P-00001", "--zadaj", "P-00002",
                         "--tema", "Rokovi isporuke u B2B", stdout=out)
        sefov = AgentPlan.objects.get(persona=mila)
        izvrsiocev = AgentPlan.objects.get(persona=jovan)
        assert izvrsiocev.status == PS.COMPLETED
        assert sefov.status == PS.COMPLETED
        nacrt = izvrsiocev.steps.get(sequence=1).output_json
        assert nacrt["item"] and nacrt["tekst"].strip()
        assert sefov.steps.get(sequence=2).status == SS.DONE

    def test_upwards_order_is_refused_at_the_command(self, ekipa):
        with pytest.raises(CommandError, match="ne odgovara"):
            call_command("plan", "--persona", "P-00002", "--zadaj", "P-00001",
                         "--tema", "Bilo šta", stdout=io.StringIO())

    def test_submit_without_a_channel_stops_with_a_reason(self, ekipa, poslovi):
        mila, jovan, _ = ekipa
        with bind(actor_id="user:op"):
            plan = plans.start(jovan, "Objavi", [
                {"handler": "content.draft", "input": {"tema": "Rokovi"}},
                {"handler": "content.submit", "description": "Predloži objavu"},
            ], actor="user:op")
            plans.advance(plan)
        plan.refresh_from_db()
        assert plan.status == PS.ABANDONED
        assert "nema nalog" in plan.steps.get(sequence=2).output_json["reason"]


def test_draft_says_who_wrote_it(ekipa):
    """Lokalni šablon je ispravna rezerva, ali mora da se vidi (ADR-0024)."""
    mila, jovan, _ = ekipa
    with bind(actor_id="user:slobodan"):
        call_command("plan", "--persona", "P-00001", "--zadaj", "P-00002",
                     "--tema", "Rokovi isporuke u B2B", stdout=io.StringIO())
    nacrt = AgentPlan.objects.get(persona=jovan).steps.get(sequence=1).output_json
    assert nacrt["model"] == "local/template-v1"        # bez ključa piše šablon
