"""ADR-0015 — sandučić persone na Mailcow-u.

  - adresa iz imena (bez dijakritika i „(AI)”), sudar imena dobija broj;
  - lozinka se izvodi i nigde ne upisuje; bez tajne nema lozinke;
  - otvaranje je idempotentno i ne radi bez MAILCOW_ENABLED;
  - dolazna pošta se čuva jednom (Message-ID), sa rokom čuvanja teksta;
  - hladna pošta sa domena agenata i dalje odbijena.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.context import bind
from apps.channels import mailbox
from apps.channels.models import ChannelAccount, MailMessage
from apps.runtime.adapters.mail import is_primary_domain
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

RAW = (b"From: =?utf-8?q?Portal_Nabavke?= <noreply@portal.rs>\r\n"
       b"To: mila.vukovic@webkorporacija.com\r\nSubject: Potvrdite registraciju\r\n"
       b"Message-ID: <abc123@portal.rs>\r\nDate: Tue, 22 Sep 2026 10:00:00 +0200\r\n"
       b"Content-Type: text/plain; charset=utf-8\r\n\r\nKliknite na link za potvrdu.\r\n")


@pytest.fixture
def mc(settings, monkeypatch):
    settings.MAILCOW_ENABLED = True
    settings.MAILCOW_URL = "https://mail.primer.rs"
    settings.AGENT_MAIL_DOMAIN = "webkorporacija.com"
    monkeypatch.setenv("MAILCOW_API_KEY", "kljuc")
    monkeypatch.setenv("MAILBOX_PASSWORD_SECRET", "tajna-za-lozinke")
    calls = []

    def fake(path, body=None):
        calls.append((path, body))
        return [{"type": "success", "msg": ["mailbox_added", body and body["local_part"]]}]

    monkeypatch.setattr(mailbox, "_api", fake)
    return calls


def test_address_from_name(mila, mc):
    assert mailbox.local_part(mila) == "mila.vukovic"
    assert mailbox.address_for(mila) == "mila.vukovic@webkorporacija.com"


def test_open_is_idempotent_and_password_not_stored(mila, mc):
    with bind(actor_id="user:boss"):
        a = mailbox.provision(mila, actor="user:boss")
        b = mailbox.provision(mila, actor="user:boss")
    assert a.pk == b.pk and len(mc) == 1
    body = mc[0][1]
    assert body["local_part"] == "mila.vukovic" and body["domain"] == "webkorporacija.com"
    pw = body["password"]
    assert pw == mailbox.password_for(mila) and len(pw) >= 20
    acc = ChannelAccount.objects.get(pk=a.pk)
    assert pw not in str(acc.__dict__) and acc.credential_ref == mailbox.MAILBOX_REF
    assert acc.channel_type == E.ChannelType.EMAIL and acc.sending_domain == ""


def test_disabled_writes_nothing(mila, mc, settings):
    settings.MAILCOW_ENABLED = False
    with bind(actor_id="user:boss"), pytest.raises(mailbox.MailboxError) as e:
        mailbox.provision(mila, actor="user:boss")
    assert e.value.code == "MAILCOW_DISABLED" and not mc
    assert mailbox.mailbox_of(mila) is None


def test_no_secret_no_password(mila, mc, monkeypatch):
    monkeypatch.delenv("MAILBOX_PASSWORD_SECRET")
    with pytest.raises(mailbox.MailboxError) as e:
        mailbox.password_for(mila)
    assert e.value.code == "CREDENTIAL_MISSING"


def test_mailcow_rejection_is_reported(mila, mc, monkeypatch):
    monkeypatch.setattr(mailbox, "_api",
                        lambda path, body=None: [{"type": "danger", "msg": ["domain_invalid"]}])
    with bind(actor_id="user:boss"), pytest.raises(mailbox.MailboxError) as e:
        mailbox.provision(mila, actor="user:boss")
    assert e.value.code == "MAILCOW_REJECTED" and "domain_invalid" in e.value.detail
    assert mailbox.mailbox_of(mila) is None


def test_inbound_stored_once(mila, mc):
    with bind(actor_id="user:boss"):
        acc = mailbox.provision(mila, actor="user:boss")
        now = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
        m = mailbox.store_inbound(acc, RAW, now)
        again = mailbox.store_inbound(acc, RAW, now)
    assert again is None and MailMessage.objects.count() == 1
    assert m.subject == "Potvrdite registraciju" and "Portal Nabavke" in m.from_addr
    assert m.body_text.startswith("Kliknite") and m.body_retained_until > now
    assert m.direction == E.MailDirection.INBOUND


def test_poll_uses_imap(mila, mc, monkeypatch):
    with bind(actor_id="user:boss"):
        acc = mailbox.provision(mila, actor="user:boss")
    seen = {}

    class FakeIMAP:
        def __init__(self, host, port, timeout):
            seen["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            seen["login"] = (user, pw)

        def select(self, box):
            pass

        def search(self, *a):
            return "OK", [b"1"]

        def fetch(self, num, what):
            return "OK", [(b"1 (RFC822)", RAW)]

    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", FakeIMAP)
    with bind(actor_id="service:mail-poll"):
        assert mailbox.poll(acc) == 1
    assert seen["host"] == "mail.primer.rs"
    assert seen["login"] == ("mila.vukovic@webkorporacija.com", mailbox.password_for(mila))


def test_agent_domain_is_still_primary_for_cold_mail(settings):
    assert is_primary_domain("webkorporacija.com")
