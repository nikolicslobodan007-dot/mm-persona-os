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
