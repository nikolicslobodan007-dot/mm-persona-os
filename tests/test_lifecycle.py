"""F9 — status persone, merenje modela. ADR-0011."""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command

from apps.behaviour.models import BehaviourState
from apps.observability.models import AuditEvent
from apps.personas import lifecycle
from apps.personas.models import Persona
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
S, R = E.PersonaStatus, E.Role


def _p():
    return Persona.objects.get(public_id="P-00001")


class TestTransitions:
    def test_operator_activates_with_reason_and_audit(self, mila):
        p = lifecycle.change_status(mila, S.ACTIVE, actor="user:op", roles={R.OPERATOR},
                                    reason="Pilot A počinje")
        assert p.status == S.ACTIVE and p.activated_at is not None and p.version == 2
        st = BehaviourState.objects.get(persona=p)
        assert st.next_wake_at is not None
        ev = AuditEvent.objects.filter(event_key="persona.status.changed").latest("id")
        assert "Pilot A počinje" in str(ev.payload)

    def test_reason_required(self, mila):
        with pytest.raises(lifecycle.LifecycleError):
            lifecycle.change_status(mila, S.ACTIVE, actor="user:op", roles={R.OPERATOR},
                                    reason="  ")

    def test_viewer_cannot(self, mila):
        with pytest.raises(lifecycle.LifecycleError) as e:
            lifecycle.change_status(mila, S.ACTIVE, actor="user:v", roles={R.VIEWER},
                                    reason="x")
        assert e.value.code == "FORBIDDEN"

    def test_suspended_needs_trust_safety(self, mila):
        Persona.objects.filter(pk=mila.pk).update(status=S.SUSPENDED)
        with pytest.raises(lifecycle.LifecycleError):
            lifecycle.change_status(_p(), S.READY, actor="user:a",
                                    roles={R.SYSTEM_ADMIN, R.OPERATOR}, reason="x")
        p = lifecycle.change_status(_p(), S.READY, actor="user:ts", roles={R.TRUST_SAFETY},
                                    reason="Incident zatvoren")
        assert p.status == S.READY

    def test_unknown_transition(self, mila):
        with pytest.raises(lifecycle.LifecycleError):
            lifecycle.change_status(mila, S.DEGRADED, actor="user:a", roles=set(R),
                                    reason="x")

    def test_pause_and_resume(self, mila):
        lifecycle.change_status(mila, S.ACTIVE, actor="user:op", roles={R.OPERATOR}, reason="a")
        lifecycle.change_status(_p(), S.PAUSED, actor="user:op", roles={R.OPERATOR}, reason="b")
        assert lifecycle.allowed_targets(_p(), {R.OPERATOR}) == [S.ACTIVE]

    def test_scheduler_wakes_only_active(self, mila):
        from django.utils import timezone

        from apps.behaviour import scheduler

        BehaviourState.objects.filter(persona=mila).update(next_wake_at=timezone.now())
        assert not scheduler.scan_due(timezone.now())
        lifecycle.change_status(mila, S.ACTIVE, actor="user:op", roles={R.OPERATOR}, reason="a")
        assert [d.persona_public_id for d in scheduler.scan_due(timezone.now())] == ["P-00001"]


class TestConsoleAndApi:
    def test_console_activation(self, mila):
        from django.contrib.auth.models import Group, User
        from django.test import Client

        from tests.test_console import _login

        u = User.objects.create_user("boss", password="Tajna-lozinka-1")
        u.groups.add(Group.objects.get(name=R.SYSTEM_ADMIN.value))
        call_command("console_totp", user="boss", stdout=io.StringIO())
        c = _login(Client(), u)
        html = c.get("/console/personas/P-00001").content.decode()
        assert "→ ACTIVE" in html and "Scheduler je ne budi" in html
        c.post("/console/personas/P-00001/status", {"to": "ACTIVE", "reason": "Pilot"})
        assert _p().status == S.ACTIVE

    def test_api(self, mila):
        from django.contrib.auth.models import Group, User
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        u = User.objects.create_user("pm", password="x")
        u.groups.add(Group.objects.get(name=R.PERSONA_MANAGER.value))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}",
                      HTTP_X_ACTOR_ID="user:pm", HTTP_X_REQUEST_ID="test-f9-0001",
                      HTTP_TRACEPARENT="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
        r = c.post("/api/v1/personas/P-00001/status", {"to": "ACTIVE", "reason": "Pilot"},
                   format="json", HTTP_IDEMPOTENCY_KEY="status-00001")
        assert r.status_code == 200, r.content
        assert r.json()["data"]["status"] == "ACTIVE"
        r = c.post("/api/v1/personas/P-00001/status", {"to": "ARCHIVED", "reason": "x"},
                   format="json", HTTP_IDEMPOTENCY_KEY="status-00002")
        assert r.status_code in (400, 403)


def test_content_eval_runs_locally(mila):
    out = io.StringIO()
    call_command("content_eval", persona="P-00001", topics="AI u prodaji;Rokovi", stdout=out)
    text = out.getvalue()
    assert "local/template-v1" in text and "2/2" in text
    from apps.content.models import ContentItem

    assert not ContentItem.objects.exists()


def test_llm_route_and_eval_with_fake_claude(mila, monkeypatch):
    from apps.llm_gateway import gateway
    from apps.llm_gateway.models import LLMRoute

    out = io.StringIO()
    call_command("llm_route", "add", provider="anthropic", model="claude-sonnet-5",
                 in_usd="2", out_usd="10", stdout=out)
    r = LLMRoute.objects.get(provider="anthropic")
    assert not r.is_enabled and r.data_training_allowed
    assert (r.input_price_micro_eur_per_1k, r.output_price_micro_eur_per_1k) == (1720, 8600)
    sent = []

    def fake(url, headers, body, timeout):
        sent.append(body)
        return {"content": [{"type": "text", "text": f"Tekst o temi {len(sent)} — čista šljiva."}],
                "usage": {"input_tokens": 900, "output_tokens": 120}, "stop_reason": "end_turn"}

    monkeypatch.setattr(gateway, "_post_json", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    out = io.StringIO()
    call_command("content_eval", persona="P-00001", topics="A;B", include_disabled=True,
                 stdout=out)
    assert "LLM_EXTERNAL_DISABLED" in out.getvalue() and not sent  # bez dozvole nema poziva
    out = io.StringIO()
    call_command("content_eval", persona="P-00001", topics="A;B", include_disabled=True,
                 allow_external=True, stdout=out)
    assert "anthropic/claude-sonnet-5  2/2" in out.getvalue()
    assert "temperature" not in sent[0] and sent[0]["thinking"] == {"type": "disabled"}
    call_command("llm_route", "enable", provider="anthropic", model="claude-sonnet-5",
                 stdout=io.StringIO())
    assert LLMRoute.objects.get(provider="anthropic").is_enabled
