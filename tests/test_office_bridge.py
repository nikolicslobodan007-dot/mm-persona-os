"""Virtual Office bridge V1.2: auth, sanitization, cursor and portrait isolation."""

from __future__ import annotations

import re

import pytest
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.observability.models import AuditEvent
from apps.orchestration.models import AgentPlan
from apps.personas.models import Persona, PersonaDossier
from apps.visuals.models import MediaAsset, VisualProfile
from common import enums as E
from console.auth import SESSION_OTP
from tests.conftest import requires_db

pytestmark = [requires_db]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _person(public_id):
    return Persona.objects.create(
        public_id=public_id,
        slug="office-" + public_id.lower(),
        display_name="Test AI saradnik (AI)",
        persona_type=E.PersonaType.AI_EXPERT.value,
        disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE.value,
        primary_locale="sr-Latn", timezone="Europe/Belgrade",
    )


def _signed_client(user):
    c = Client()
    c.force_login(user)
    session = c.session
    session[SESSION_OTP] = True
    session.save()
    return c


@pytest.fixture
def office_client(mila):
    user = User.objects.create_user("office_viewer", password="long-test-password")
    user.groups.add(Group.objects.get(name=E.Role.VIEWER.value))
    return _signed_client(user)


def test_unauthenticated_returns_json_401(mila):
    r = Client().get("/console/office/api/v1/agents")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == E.ErrorCode.UNAUTHENTICATED.value
    assert "Content-Security-Policy" in r


def test_totp_and_role_required(mila):
    no_role = User.objects.create_user("office_norole", password="long-test-password")
    c = Client()
    c.force_login(no_role)
    assert c.get("/console/office/api/v1/summary").status_code == 401
    session = c.session
    session[SESSION_OTP] = True
    session.save()
    assert c.get("/console/office/api/v1/summary").status_code == 403


def test_read_only_summary_and_agent(mila, office_client):
    r = office_client.get("/console/office/api/v1/summary")
    assert r.status_code == 200
    assert r.json()["agents"]["total"] >= 1
    r = office_client.get("/console/office/api/v1/agents")
    assert r.status_code == 200
    p = next(x for x in r.json()["items"] if x["public_id"] == mila.public_id)
    assert "id" not in p and "metadata" not in p
    assert p["runtime_environment"] == mila.runtime_environment
    assert p["status"] == mila.status
    assert "script-src 'self'" in r["Content-Security-Policy"]


def test_private_fields_and_plan_goal_never_escape(mila, office_client):
    secret = "TOP SECRET: client account and project code"
    mila.metadata = {"secret": secret}
    mila.save(update_fields=["metadata"])
    PersonaDossier.objects.update_or_create(
        persona=mila, defaults={"birth_place": secret, "appearance_prompt": secret}
    )
    AgentPlan.objects.create(
        public_id="PLN-01OFFICE", persona=mila,
        status=E.PlanStatus.ACTIVE.value, goal=secret, priority=2,
    )
    r = office_client.get(f"/console/office/api/v1/agents/{mila.public_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["active_plan"]["goal_excerpt"] is None
    assert secret not in r.content.decode()
    assert "metadata" not in body and "birth_place" not in body
    assert "id" not in body and "pk" not in body


def test_cursor_is_session_bound(mila, office_client):
    _person("P-00999")
    first = office_client.get("/console/office/api/v1/agents?limit=1")
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor and not re.search(r"P-\d{5}", cursor)  # opaque token; ne curi public_id (P-#####)
    second = office_client.get("/console/office/api/v1/agents?limit=1&cursor=" + cursor)
    assert second.status_code == 200
    other = _signed_client(User.objects.get(username="office_viewer"))
    denied = other.get("/console/office/api/v1/agents?limit=1&cursor=" + cursor)
    assert denied.status_code == 400
    changed = office_client.get("/console/office/api/v1/agents?limit=2&cursor=" + cursor)
    assert changed.status_code == 400


def test_portrait_proxy_rejects_other_person_and_non_reference(mila, office_client):
    other = _person("P-00998")
    asset = MediaAsset.objects.create(
        public_id="IMG-P00001-0001", persona=mila,
        kind=E.AssetKind.FACE_REFERENCE.value,
        storage_key="not-a-real-storage-key", mime_type="image/jpeg",
        sha256="a" * 64, origin="generated",
    )
    VisualProfile.objects.create(persona=other, style_prompt="", reference_asset=asset)
    r = office_client.get(f"/console/office/portraits/{other.public_id}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == E.ErrorCode.NOT_FOUND.value
    asset.kind = E.AssetKind.PHOTO.value
    asset.save(update_fields=["kind"])
    VisualProfile.objects.update_or_create(
        persona=mila, defaults={"style_prompt": "", "reference_asset": asset}
    )
    assert office_client.get(f"/console/office/portraits/{mila.public_id}").status_code == 404


def test_events_exclude_actor_ref_payload_and_db_id(mila, office_client):
    AuditEvent.objects.create(
        occurred_at=timezone.now(), severity=E.AuditSeverity.INFO.value,
        event_key="plan.delegated", persona=mila, actor_ref="user:private",
        payload={"secret": "private data"}, payload_hash="x" * 64,
    )
    r = office_client.get("/console/office/api/v1/events")
    assert r.status_code == 200
    event = r.json()["items"][0]
    assert set(event) == {
        "occurred_at", "severity", "event_key", "persona_public_id", "actor_role"
    }
    assert "private" not in r.content.decode()
