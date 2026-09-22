"""ADR-0014 — persona uči iz odluka urednika.

  - odbijanje sa razlogom i izmena teksta postaju pouka;
  - pouka „za sve” ulazi u prompt svake persone, i nove;
  - isključena pouka više ne ulazi u prompt;
  - odobrenje bez izmene ne pravi pouku; ista pouka se ne duplira.
"""

from __future__ import annotations

import io
import time

import pytest
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client

from api.context import bind
from apps.content import lessons
from apps.content import service as content
from apps.content.models import EditorialLesson
from apps.llm_gateway import gateway
from apps.policy.models import ApprovalRequest
from common import enums as E
from console import totp
from console.models import OperatorTOTP
from tests.conftest import requires_db

pytestmark = [requires_db]


@pytest.fixture(autouse=True)
def _cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def boss(mila):
    u = User.objects.create_user("boss", password="Tajna-lozinka-1")
    u.groups.add(Group.objects.get(name=E.Role.SYSTEM_ADMIN.value))
    u.user_permissions.add(*Group.objects.get(name=E.Role.OPERATOR.value).permissions.all())
    call_command("console_totp", user="boss", stdout=io.StringIO())
    call_command("pilot_setup", persona="P-00001", actor="user:boss", stdout=io.StringIO())
    return u


def _login(user):
    c = Client()
    c.post("/console/login", {"username": user.username, "password": "Tajna-lozinka-1"})
    rec = OperatorTOTP.objects.get(user=user)
    code = totp.code_at(totp.secret_for(user.username, rec.version), int(time.time() // totp.STEP))
    c.post("/console/login/2fa", {"code": code})
    return c


def _pending(mila):
    with bind(actor_id="user:op"):
        item, sent = content.draft_now(mila, topic=f"Tema {EditorialLesson.objects.count()}"
                                       f"{ApprovalRequest.objects.count()} o rokovima")
    assert sent
    return ApprovalRequest.objects.get(status=E.ApprovalStatus.PENDING)


def test_describe_edit():
    d = lessons.describe_edit("**Mila** B2B kupci biraju po prideva iz prezentacije.",
                              "B2B kupci biraju po pridevima iz prezentacije.")
    assert d == "ukloni «**Mila**»; «prideva» → «pridevima»"


def test_reject_with_reason_becomes_lesson(boss, mila):
    ap = _pending(mila)
    c = _login(boss)
    c.post(f"/console/approvals/{ap.public_id}/decide",
           {"decision": "REJECTED", "reason": "Previše uopšteno, treba primer", "learn": "1"})
    les = EditorialLesson.objects.get()
    assert les.persona_id == mila.pk and les.kind == "rejected"
    assert "Previše uopšteno" in lessons.prompt_section(mila)


def test_edit_becomes_lesson_for_everyone(boss, mila):
    ap = _pending(mila)
    text = ap.action.input_json["text"]
    c = _login(boss)
    c.post(f"/console/approvals/{ap.public_id}/decide",
           {"decision": "APPROVED_WITH_CHANGES", "text": text.replace("—", "–", 1) + " Hvala.",
            "reason": "", "learn": "1", "everyone": "1"})
    les = EditorialLesson.objects.get()
    assert les.persona_id is None and les.kind == "edited"
    assert "«Hvala.»" in les.text or "Hvala." in les.text
    assert "[svi]" in lessons.prompt_section(mila)


def test_unchecked_learn_and_plain_approval_teach_nothing(boss, mila):
    ap = _pending(mila)
    c = _login(boss)
    c.post(f"/console/approvals/{ap.public_id}/decide",
           {"decision": "REJECTED", "reason": "šablon, ključ nije radio"})
    ap2 = _pending(mila)
    c.post(f"/console/approvals/{ap2.public_id}/decide", {"decision": "APPROVED", "learn": "1"})
    assert not EditorialLesson.objects.exists()


def test_lessons_reach_the_model_and_toggle_off(boss, mila, settings, monkeypatch):
    settings.LLM_EXTERNAL_ENABLED = True
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    from apps.llm_gateway.models import LLMRoute

    LLMRoute.objects.create(purpose=E.LLMPurpose.CONTENT_DRAFT, name="C", provider="anthropic",
                            model_key="m", priority=1, data_training_allowed=True)
    prompts = []

    def fake(url, headers, body, timeout):
        prompts.append(body["messages"][0]["content"])
        return {"content": [{"type": "text", "text": f"Tekst broj {len(prompts)} o nabavci."}],
                "usage": {"input_tokens": 1, "output_tokens": 1}, "stop_reason": "end_turn"}

    monkeypatch.setattr(gateway, "_post_json", fake)
    with bind(actor_id="user:boss"):
        les = lessons.learn(persona=mila, kind="manual", actor="user:boss",
                            reason="Koristi srpske navodnice „ i ”.", everyone=True)
        content.draft(mila, topic="Navodnice jedan")
    assert "Koristi srpske navodnice" in prompts[-1]
    c = _login(boss)
    c.post(f"/console/lessons/{les.id}/toggle", {"back": "/console/personas/P-00001"})
    with bind(actor_id="user:boss"):
        content.draft(mila, topic="Navodnice dva")
    assert "navodnice" not in prompts[-1]


def test_same_lesson_is_not_duplicated(mila):
    with bind(actor_id="user:boss"):
        for _ in range(2):
            lessons.learn(persona=mila, kind="manual", actor="user:boss", reason="Bez emodžija.")
    assert EditorialLesson.objects.count() == 1


def test_persona_page_shows_lessons_and_adds_rule(boss, mila):
    c = _login(boss)
    c.post("/console/personas/P-00001/lessons", {"text": "Kraće rečenice.", "everyone": "1"})
    page = c.get("/console/personas/P-00001").content.decode()
    assert "Pouke urednika" in page and "Kraće rečenice." in page
