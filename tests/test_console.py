"""F8 — Kontrolna tabla. ADR-0010.

  - bez lozinke I drugog faktora nema nijedne strane;
  - isti TOTP kod se ne prima dvaput; 5 promašaja → zaključano;
  - korisnik bez uloge ne ulazi;
  - odluke idu kroz isti servis kao API (isti audit, isti akter);
  - CSRF je obavezan na svakom upisu; `next` ne vodi van konzole.
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
from apps.content import service as content
from apps.content.models import ContentItem
from apps.policy.models import ApprovalRequest, KillSwitch
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
    return u


def _code(user, offset=0):
    rec = OperatorTOTP.objects.get(user=user)
    step = int(time.time() // totp.STEP) + offset
    return totp.code_at(totp.secret_for(user.username, rec.version), step)


def _login(c, user, pw="Tajna-lozinka-1"):
    r = c.post("/console/login", {"username": user.username, "password": pw})
    assert r.status_code == 302 and "/console/login/2fa" in r["Location"]
    r = c.post("/console/login/2fa", {"code": _code(user)})
    assert r.status_code == 302 and r["Location"] == "/console/"
    return c


@pytest.fixture
def pending(mila):
    call_command("pilot_setup", persona="P-00001", actor="user:boss", stdout=io.StringIO())
    from apps.channels.models import ChannelAccount

    sb = ChannelAccount.objects.get(persona=mila, channel_type=E.ChannelType.SANDBOX)
    with bind(actor_id="user:op"):
        item = content.draft(mila, topic="Konzola proba")
        content.submit(item, sb)
    return item, ApprovalRequest.objects.get(status=E.ApprovalStatus.PENDING)


class TestAuth:
    def test_everything_requires_login(self, db):
        for path in ("/console/", "/console/approvals", "/console/costs",
                     "/console/personas/P-00001"):
            r = Client().get(path)
            assert r.status_code == 302 and r["Location"].startswith("/console/login")

    def test_password_alone_is_not_enough(self, boss):
        c = Client()
        c.post("/console/login", {"username": "boss", "password": "Tajna-lozinka-1"})
        assert c.get("/console/").status_code == 302

    def test_full_login_and_security_headers(self, boss):
        c = _login(Client(), boss)
        r = c.get("/console/")
        assert r.status_code == 200
        assert "frame-ancestors 'none'" in r["Content-Security-Policy"]
        assert r["Cache-Control"] == "no-store"
        assert "Probni režim" in r.content.decode()

    def test_code_cannot_be_replayed(self, boss):
        code = _code(boss)
        assert totp.verify(boss, code)
        assert not totp.verify(boss, code)

    def test_lockout_after_five_failures(self, boss):
        c = Client()
        for _ in range(5):
            c.post("/console/login", {"username": "boss", "password": "pogresno"})
        r = c.post("/console/login", {"username": "boss", "password": "Tajna-lozinka-1"})
        assert r.status_code == 200 and "Previše" in r.content.decode()

    def test_user_without_role_is_rejected(self, db):
        User.objects.create_user("niko", password="Tajna-lozinka-1")
        r = Client().post("/console/login", {"username": "niko",
                                             "password": "Tajna-lozinka-1"})
        assert r.status_code == 200 and "Pogrešno" in r.content.decode()

    def test_no_totp_enrolled_means_no_entry(self, mila):
        u = User.objects.create_user("bez2fa", password="Tajna-lozinka-1")
        u.groups.add(Group.objects.get(name=E.Role.OPERATOR.value))
        r = Client().post("/console/login", {"username": "bez2fa",
                                             "password": "Tajna-lozinka-1"})
        assert "console_totp" in r.content.decode()

    def test_next_cannot_leave_console(self, boss):
        c = Client()
        c.post("/console/login?next=https://zlo.example/", {"username": "boss",
                                                             "password": "Tajna-lozinka-1",
                                                             "next": "https://zlo.example/"})
        r = c.post("/console/login/2fa", {"code": _code(boss), "next": "https://zlo.example/"})
        assert r["Location"] == "/console/"

    def test_csrf_required(self, boss, pending):
        _, ap = pending
        c = Client(enforce_csrf_checks=True)
        # prijava bez CSRF tokena pada već na prvom koraku
        assert c.post("/console/login", {"username": "boss",
                                         "password": "Tajna-lozinka-1"}).status_code == 403


class TestApprovals:
    def test_page_shows_text_and_channel(self, boss, pending):
        item, ap = pending
        c = _login(Client(), boss)
        html = c.get("/console/approvals").content.decode()
        assert "Konzola proba" in html and "SANDBOX" in html and ap.public_id in html

    def test_approve(self, boss, pending):
        item, ap = pending
        c = _login(Client(), boss)
        r = c.post(f"/console/approvals/{ap.public_id}/decide", {"decision": "APPROVED"})
        assert r.status_code == 302
        ap.refresh_from_db()
        item.refresh_from_db()
        assert ap.status == E.ApprovalStatus.APPROVED and ap.decided_by == "user:boss"
        assert item.status == E.ContentStatus.APPROVED

    def test_edit_then_approve(self, boss, pending):
        item, ap = pending
        c = _login(Client(), boss)
        c.post(f"/console/approvals/{ap.public_id}/decide",
               {"decision": "APPROVED_WITH_CHANGES",
                "text": "Kraće.\r\n\r\n— Mila Vuković · AI persona"})
        item.refresh_from_db()
        assert item.body == "Kraće.\n\n— Mila Vuković · AI persona" and item.version == 2

    def test_edit_cannot_smuggle_prohibited_text(self, boss, pending):
        item, ap = pending
        c = _login(Client(), boss)
        c.post(f"/console/approvals/{ap.public_id}/decide",
               {"decision": "APPROVED_WITH_CHANGES", "text": "Ja sam prava osoba."})
        item.refresh_from_db()
        assert item.status != E.ContentStatus.APPROVED

    def test_reject_needs_reason(self, boss, pending):
        item, ap = pending
        c = _login(Client(), boss)
        c.post(f"/console/approvals/{ap.public_id}/decide", {"decision": "REJECTED"})
        ap.refresh_from_db()
        assert ap.status == E.ApprovalStatus.PENDING
        c.post(f"/console/approvals/{ap.public_id}/decide",
               {"decision": "REJECTED", "reason": "Previše uopšteno"})
        item.refresh_from_db()
        assert item.status == E.ContentStatus.REJECTED

    def test_viewer_cannot_decide(self, mila, pending):
        _, ap = pending
        u = User.objects.create_user("gledalac", password="Tajna-lozinka-1")
        u.groups.add(Group.objects.get(name=E.Role.VIEWER.value))
        call_command("console_totp", user="gledalac", stdout=io.StringIO())
        c = _login(Client(), u)
        assert "nemaš dozvolu" in c.get("/console/approvals").content.decode()
        c.post(f"/console/approvals/{ap.public_id}/decide", {"decision": "APPROVED"})
        ap.refresh_from_db()
        assert ap.status == E.ApprovalStatus.PENDING


class TestKillSwitchAndPages:
    def test_stop_and_release(self, boss, pending):
        item, _ = pending
        c = _login(Client(), boss)
        c.post("/console/kill-switch", {"operation": "activate", "scope_target": "GLOBAL:",
                                        "reason": "drill"})
        ks = KillSwitch.objects.get(is_active=True)
        assert ks.activated_by == "user:boss"
        assert "Aktivan kill-switch" in c.get("/console/").content.decode()
        c.post("/console/kill-switch", {"operation": "clear", "kill_switch_id": str(ks.id),
                                        "reason": "drill gotov"})
        ks.refresh_from_db()
        assert not ks.is_active and ks.released_by == "user:boss"

    def test_persona_scope(self, boss, mila):
        c = _login(Client(), boss)
        c.post("/console/kill-switch", {"operation": "activate",
                                        "scope_target": "PERSONA:P-00001", "reason": "x"})
        assert KillSwitch.objects.get(is_active=True).target_ref == "P-00001"

    def test_all_pages_render(self, boss, pending):
        item, ap = pending
        c = _login(Client(), boss)
        for path in ("/console/", "/console/approvals", "/console/content",
                     "/console/content?status=IN_REVIEW", "/console/personas/P-00001",
                     f"/console/actions/{ap.action.public_id}", "/console/costs",
                     "/console/incidents", "/console/org"):
            r = c.get(path)
            assert r.status_code == 200, path
        assert c.get("/console/personas/P-99999").status_code == 404
        assert ContentItem.objects.count() == 1


class TestDraftNow:
    """ADR-0012 — „Napiši nacrt sada” iz konzole."""

    @pytest.fixture
    def ready(self, mila):
        call_command("pilot_setup", persona="P-00001", actor="user:boss", stdout=io.StringIO())
        return mila

    def test_draft_goes_to_approval(self, boss, ready):
        c = _login(Client(), boss)
        assert "Napiši nacrt sada" in c.get("/console/personas/P-00001").content.decode()
        r = c.post("/console/personas/P-00001/draft", {"topic": "Ponuda za veleprodaju"})
        assert r.status_code == 302 and r["Location"] == "/console/approvals"
        item = ContentItem.objects.get(title="Ponuda za veleprodaju")
        assert item.run.reason_code == E.DecisionReason.OPERATOR_TASK
        ap = ApprovalRequest.objects.get(status=E.ApprovalStatus.PENDING)
        assert ap.action.channel_account.channel_type == E.ChannelType.SANDBOX
        assert "Ponuda za veleprodaju" in c.get("/console/approvals").content.decode() or \
            item.body[:30] in c.get("/console/approvals").content.decode()

    def test_empty_topic_uses_persona_niche(self, boss, ready):
        c = _login(Client(), boss)
        c.post("/console/personas/P-00001/draft", {"topic": ""})
        item = ContentItem.objects.get()
        assert item.title in {"AI", "B2B", "Prodaja"}

    def test_daily_limit(self, boss, ready, monkeypatch):
        monkeypatch.setattr(content, "MANUAL_DRAFTS_PER_DAY", 2)
        c = _login(Client(), boss)
        for t in ("Tema jedan o kupcima", "Tema dva o rokovima", "Tema tri o ceni"):
            c.post("/console/personas/P-00001/draft", {"topic": t})
        assert ContentItem.objects.count() == 2

    def test_not_for_paused_persona(self, boss, ready):
        from apps.personas.models import Persona

        Persona.objects.filter(pk=ready.pk).update(status=E.PersonaStatus.PAUSED.value)
        c = _login(Client(), boss)
        assert "Napiši nacrt sada" not in c.get("/console/personas/P-00001").content.decode()
        c.post("/console/personas/P-00001/draft", {"topic": "Nešto"})
        assert not ContentItem.objects.exists()

    def test_viewer_cannot_draft(self, ready):
        u = User.objects.create_user("gledalac", password="Tajna-lozinka-1")
        u.groups.add(Group.objects.get(name=E.Role.VIEWER.value))
        call_command("console_totp", user="gledalac", stdout=io.StringIO())
        c = _login(Client(), u)
        c.post("/console/personas/P-00001/draft", {"topic": "Nešto"})
        assert not ContentItem.objects.exists()


def test_templates_have_no_inline_styles_or_scripts():
    """CSP je `style-src 'self'; script-src 'self'` — inline stil bi pregledač tiho ignorisao."""
    import pathlib
    import re

    for f in pathlib.Path("console/templates").rglob("*.html"):
        text = f.read_text(encoding="utf-8")
        assert 'style="' not in text, f
        assert "<style" not in text and not re.search(r"<script(?![^>]*\bsrc=)", text), f


class TestOrgConsole:
    """ADR-0017 — organizacija i dosije iz konzole."""

    @pytest.fixture
    def firma(self, mila):
        with bind(actor_id="user:boss"):
            call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
        return mila

    def test_org_page_shows_sectors_and_seats(self, boss, firma):
        c = _login(Client(), boss)
        html = c.get("/console/org").content.decode()
        assert "Marketing i sadržaj" in html and "Urednik sadržaja" in html
        assert "Mila Vuković (AI)" in html

    def test_reassign_from_console(self, boss, firma):
        from apps.personas import org

        c = _login(Client(), boss)
        r = c.post("/console/personas/P-00001/assign", {"position": "SEF-MKT"})
        assert r.status_code == 302
        assert org.position_of(firma).code == "SEF-MKT"

    def test_dossier_written_from_console_and_minor_refused(self, boss, firma):
        from apps.personas import org

        c = _login(Client(), boss)
        c.post("/console/personas/P-00001/dossier",
               {"residence": "Subotica", "height_cm": "170", "hobbies": "trčanje, čitanje"})
        d = org.dossier_of(firma)
        assert d.residence == "Subotica" and d.height_cm == 170
        assert d.hobbies == ["trčanje", "čitanje"]
        c.post("/console/personas/P-00001/dossier", {"birth_date": "2014-01-01"})
        firma.refresh_from_db()
        assert firma.birth_date_model.year == 1991


class TestLikConsole:
    """ADR-0018 — kartica „Lik" i prikaz slike iz storage-a."""

    def test_card_shows_portrait_and_serves_image(self, boss, mila, settings, monkeypatch):
        from apps.visuals import generator, storage

        settings.IMAGE_ENABLED = True
        settings.IMAGE_MODEL = "gpt-image-2"
        monkeypatch.setenv("OPENAI_API_KEY", "kljuc")
        with bind(actor_id="user:boss"):
            call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
        files = {}
        monkeypatch.setattr(generator, "_call", lambda *a, **k: b"\x89PNG\r\n\x1a\nx")
        monkeypatch.setattr(storage, "put",
                            lambda data, *, key, mime: files.__setitem__(key, data) or key)
        monkeypatch.setattr(storage, "get", lambda key: files[key])
        with bind(actor_id="user:boss"):
            r = generator.make_portrait(mila, actor="user:boss")

        c = _login(Client(), boss)
        html = c.get("/console/personas/P-00001").content.decode()
        assert f"/console/assets/{r.asset.public_id}" in html
        img = c.get(f"/console/assets/{r.asset.public_id}")
        assert img.status_code == 200 and img["Content-Type"] == "image/png"
        assert img.content.startswith(b"\x89PNG")


class TestUploadConsole:
    """Dopuna ADR-0018 — otpremanje ručno napravljene slike iz konzole."""

    def test_upload_from_console(self, boss, mila, settings, monkeypatch):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.visuals import generator, storage

        settings.IMAGE_ENABLED = False          # generator ugašen, otpremanje radi
        files = {}
        monkeypatch.setattr(storage, "put",
                            lambda data, *, key, mime: files.__setitem__(key, data) or key)
        monkeypatch.setattr(storage, "get", lambda key: files[key])
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 32

        c = _login(Client(), boss)
        r = c.post("/console/personas/P-00001/upload",
                   {"slika": SimpleUploadedFile("mila.png", png, "image/png"),
                    "kao_profilna": "1"})
        assert r.status_code == 302
        asset = generator.reference_of(mila)
        assert asset is not None and asset.generation_model == generator.MANUAL_MODEL
        assert c.get(f"/console/assets/{asset.public_id}").status_code == 200
