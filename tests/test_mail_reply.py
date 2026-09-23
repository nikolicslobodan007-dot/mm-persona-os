"""ADR-0016 — sandučić prati status persone, nacrt odgovora na pristiglu poštu.

  - DRAFT → READY otvara sandučić sam, ARCHIVED ga gasi;
  - kvar Mailcow-a ne ruši promenu statusa;
  - ne odgovara se na automatske poruke, liste, `noreply@`, stare poruke,
    niti dvaput na istu;
  - odgovor je nacrt: akcija `mail.reply` čeka odobrenje, ništa ne izlazi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from api.context import bind
from apps.channels import mailbox, reply
from apps.channels.models import ChannelAccount, ChannelCapability, MailMessage
from apps.orchestration.models import Action
from apps.personas import lifecycle
from apps.personas.models import Persona
from apps.policy import service as policy_service
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
S, R = E.PersonaStatus, E.Role
NOW = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)

HUMAN = (b"From: Petar Petrovic <petar@kupac.rs>\r\n"
         b"To: mila.vukovic@webkorporacija.com\r\nSubject: Upit za rokove\r\n"
         b"Message-ID: <u1@kupac.rs>\r\nDate: Wed, 23 Sep 2026 08:00:00 +0200\r\n"
         b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
         b"Postovani, koliki su rokovi isporuke za B2B narudzbine?\r\n")


@pytest.fixture
def mc(settings, monkeypatch):
    """Mailcow uključen, API lažan — zapisuje pozive umesto da ide napolje."""
    settings.MAILCOW_ENABLED = True
    settings.MAILCOW_URL = "https://mail.primer.rs"
    settings.AGENT_MAIL_DOMAIN = "webkorporacija.com"
    settings.MAIL_AUTOREPLY = True
    monkeypatch.setenv("MAILCOW_API_KEY", "kljuc")
    monkeypatch.setenv("MAILBOX_PASSWORD_SECRET", "tajna-za-lozinke")
    calls = []

    def fake(path, body=None):
        calls.append((path, body))
        return [{"type": "success", "msg": ["ok"]}]

    monkeypatch.setattr(mailbox, "_api", fake)
    return calls


def _p():
    return Persona.objects.get(public_id="P-00001")


def _box(persona):
    """Sandučić + poverenje L2, kao posle `pilot_setup --with-mail`."""
    with bind(actor_id="user:boss"):
        acc = mailbox.provision(persona, actor="user:boss")
        policy_service.change_trust(persona, mailbox.REPLY_CAPABILITY, E.TrustLevel.L2,
                                    actor="user:ts", reason="QA")
    return acc


class TestMailboxFollowsStatus:
    def test_ready_opens_mailbox(self, mila, mc, django_capture_on_commit_callbacks):
        Persona.objects.filter(pk=mila.pk).update(status=S.DRAFT.value)
        with django_capture_on_commit_callbacks(execute=True):
            lifecycle.change_status(_p(), S.READY, actor="user:pm", roles={R.PERSONA_MANAGER},
                                    reason="Pilot")
        acc = mailbox.mailbox_of(_p())
        assert acc is not None and acc.persona_address == "mila.vukovic@webkorporacija.com"
        assert mc[0][0] == "/api/v1/add/mailbox"
        cap = ChannelCapability.objects.get(account=acc, capability=mailbox.REPLY_CAPABILITY)
        assert cap.is_enabled

    def test_archived_closes_mailbox(self, mila, mc, django_capture_on_commit_callbacks):
        acc = _box(mila)
        with django_capture_on_commit_callbacks(execute=True):
            lifecycle.change_status(_p(), S.ARCHIVED, actor="user:root",
                                    roles={R.SYSTEM_ADMIN}, reason="Kraj pilota")
        acc.refresh_from_db()
        assert acc.status == E.AccountStatus.REVOKED
        assert ("/api/v1/edit/mailbox", {"items": [acc.persona_address],
                                         "attr": {"active": "0"}}) in mc

    def test_mailcow_failure_does_not_block_status(self, mila, mc, monkeypatch,
                                                   django_capture_on_commit_callbacks):
        from apps.observability.models import AuditEvent

        Persona.objects.filter(pk=mila.pk).update(status=S.DRAFT.value)
        monkeypatch.setattr(mailbox, "_api",
                            lambda p, body=None: [{"type": "danger", "msg": ["nope"]}])
        with django_capture_on_commit_callbacks(execute=True):
            lifecycle.change_status(_p(), S.READY, actor="user:pm", roles={R.PERSONA_MANAGER},
                                    reason="Pilot")
        assert _p().status == S.READY and mailbox.mailbox_of(_p()) is None
        assert AuditEvent.objects.filter(event_key="channel.mailbox.failed").exists()


class TestSkipRules:
    def _msg(self, acc, **kw):
        with bind(actor_id="service:mail-poll"):
            m = mailbox.store_inbound(acc, HUMAN, NOW)
        for k, v in kw.items():
            setattr(m, k, v)
        m.save()
        return m

    def test_human_message_is_answered(self, mila, mc):
        acc = _box(mila)
        m = self._msg(acc)
        assert reply.skip_reason(m, now=NOW) == ""

    @pytest.mark.parametrize("meta,why", [
        ({"auto_submitted": "auto-replied"}, "AUTO_SUBMITTED"),
        ({"list_id": "<vesti.primer.rs>"}, "MAILING_LIST"),
        ({reply.REPLIED: "act_1"}, "ALREADY_REPLIED"),
    ])
    def test_metadata_rules(self, mila, mc, meta, why):
        m = self._msg(_box(mila))
        m.metadata = {**m.metadata, **meta}
        assert reply.skip_reason(m, now=NOW) == why

    def test_noreply_sender(self, mila, mc):
        m = self._msg(_box(mila), from_addr="Portal <noreply@portal.rs>")
        assert reply.skip_reason(m, now=NOW) == "NO_REPLY_SENDER"

    def test_too_old(self, mila, mc):
        m = self._msg(_box(mila))
        assert reply.skip_reason(m, now=NOW + timedelta(days=5)) == "TOO_OLD"

    def test_paused_persona_does_not_answer(self, mila, mc):
        acc = _box(mila)
        m = self._msg(acc)
        Persona.objects.filter(pk=mila.pk).update(status=S.PAUSED.value)
        m.refresh_from_db()
        assert reply.skip_reason(m, now=NOW).startswith("PERSONA_")


class TestDraft:
    def _inbound(self, acc):
        with bind(actor_id="service:mail-poll"):
            return mailbox.store_inbound(acc, HUMAN, NOW)

    def test_reply_waits_for_approval_and_sends_nothing(self, mila, mc):
        acc = _box(mila)
        m = self._inbound(acc)
        with bind(actor_id="service:mail-poll"):
            action = reply.draft_reply(m, now=NOW)
        assert action is not None and action.action_type == "mail.reply"
        assert action.status != E.ActionStatus.SUCCEEDED
        assert action.input_json["to"] == "petar@kupac.rs"
        assert action.input_json["subject"] == "Re: Upit za rokove"
        assert action.input_json["text"].strip()
        assert not MailMessage.objects.filter(direction=E.MailDirection.OUTBOUND).exists()

    def test_same_message_answered_once(self, mila, mc):
        acc = _box(mila)
        m = self._inbound(acc)
        with bind(actor_id="service:mail-poll"):
            assert reply.draft_reply(m, now=NOW) is not None
            m.refresh_from_db()
            assert reply.draft_reply(m, now=NOW) is None
        assert Action.objects.filter(action_type="mail.reply").count() == 1

    def test_daily_cap(self, mila, mc, settings):
        settings.MAIL_REPLIES_PER_DAY = 1
        acc = _box(mila)
        first = self._inbound(acc)
        second_raw = HUMAN.replace(b"<u1@kupac.rs>", b"<u2@kupac.rs>")
        with bind(actor_id="service:mail-poll"):
            second = mailbox.store_inbound(acc, second_raw, NOW)
            assert reply.draft_reply(first, now=NOW) is not None
            assert reply.draft_reply(second, now=NOW) is None
        assert Action.objects.filter(action_type="mail.reply").count() == 1

    def test_autoreply_switch_off(self, mila, mc, settings):
        settings.MAIL_AUTOREPLY = False
        acc = _box(mila)
        m = self._inbound(acc)
        with bind(actor_id="service:mail-poll"):
            assert reply.draft_replies([m], now=NOW) == 0
        assert not Action.objects.filter(action_type="mail.reply").exists()

    def test_closed_mailbox_is_not_answered(self, mila, mc):
        acc = _box(mila)
        m = self._inbound(acc)
        ChannelAccount.objects.filter(pk=acc.pk).update(status=E.AccountStatus.REVOKED.value)
        with bind(actor_id="service:mail-poll"):
            assert reply.draft_reply(m, now=NOW) is None
