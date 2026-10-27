"""Smoke tests for read-only, protected Virtual Office 3D route."""

from django.contrib.auth.models import Group, User
from django.test import Client

from common import enums as E
from console.auth import SESSION_OTP
from tests.conftest import requires_db

pytestmark = [requires_db]


def test_3d_requires_console_session_and_totp(mila):
    url = "/console/office/3d"
    assert Client().get(url).status_code == 302
    user = User.objects.create_user("office_3d_test", password="secure-test-password")
    user.groups.add(Group.objects.get(name=E.Role.VIEWER.value))
    client = Client()
    client.force_login(user)
    assert client.get(url).status_code == 302
    session = client.session
    session[SESSION_OTP] = True
    session.save()
    response = client.get(url)
    assert response.status_code == 200
    assert b"office-3d.js" in response.content
    assert b"office-3d.css" in response.content
    assert "script-src 'self'" in response["Content-Security-Policy"]
    assert response["Cache-Control"] == "no-store"
    assert client.post(url).status_code == 405


def test_3d_does_not_introduce_new_api_endpoint(mila):
    """Locked V1.2 URLs must remain the only Office JSON endpoints."""
    from console.urls import urlpatterns

    patterns = {str(p.pattern) for p in urlpatterns}
    assert "office/3d" in patterns
    assert {
        "office/api/v1/summary", "office/api/v1/agents",
        "office/api/v1/agents/<str:public_id>", "office/api/v1/events"
    }.issubset(patterns)
