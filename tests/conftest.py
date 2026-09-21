"""Podizanje Django okruženja za testove modela.

Testovi iz `test_canon.py` ne traže Django i rade i bez ovoga. Testovi iz
`test_models.py` traže učitan registar modela; oni koji dodiruju bazu
nose `@pytest.mark.django_db` i preskaču se ako baza nije dostupna.
"""

from __future__ import annotations

import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()


def _database_available() -> bool:
    """Provera ide pravo kroz drajver.

    `connection.ensure_connection()` ovde ne valja: pytest-django već je
    postavio blokadu pristupa bazi izvan `django_db`, pa bi svaka baza
    izgledala kao nedostupna i ceo DB deo bi se tiho preskakao.
    """
    from django.conf import settings

    db = settings.DATABASES["default"]
    try:
        import psycopg

        psycopg.connect(
            host=db["HOST"],
            port=db["PORT"],
            user=db["USER"],
            password=db["PASSWORD"],
            dbname="postgres",
            connect_timeout=3,
        ).close()
    except Exception:  # noqa: BLE001 — svaki neuspeh znači „nema baze"
        return False
    return True


DB_AVAILABLE = _database_available()

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE, reason="PostgreSQL nije dostupan na ovom hostu"
)


# ---------------------------------------------------------------- zajedničke fixture (F5, F6)
# Premeštene iz test_policy.py da bi ih test_runtime.py koristio bez ponovnog uvoza.

import io  # noqa: E402

from api.context import bind  # noqa: E402
from apps.channels.models import ChannelAccount, ChannelCapability  # noqa: E402
from apps.personas.models import Persona  # noqa: E402
from apps.policy import service  # noqa: E402
from common import enums as E  # noqa: E402

UA = "MercatoMasterBot/1.0 (+https://mercatomaster.com/bot; bot@mercatomaster.com)"
READ_OK = {"robots_respected": True, "user_agent_declared": UA, "rate_per_host_qps": 1.0,
           "conditional_get": True}


def _read(i=0):
    return {"url": f"https://example.com/{i}", "execution_constraints": READ_OK}


@pytest.fixture
def mila(db):
    from django.core.management import call_command

    call_command("seed_agent_001", stdout=io.StringIO())
    call_command("bootstrap_roles", stdout=io.StringIO())
    return Persona.objects.get(public_id="P-00001")


@pytest.fixture
def page(mila):
    """Kanal sa AI oznakom i publish capability-jem, uz L1 za objavu."""
    acc = ChannelAccount.objects.create(
        persona=mila, channel_type=E.ChannelType.LINKEDIN, handle="mila-page",
        identity_vehicle=E.IdentityVehicle.PAGE, status=E.AccountStatus.ACTIVE,
        disclosure_label_status=E.DisclosureLabelStatus.SET, credential_ref="vault:test",
        named_human_admin="Slobodan",
    )
    ChannelCapability.objects.create(account=acc, capability="content.publish_approved",
                                     is_enabled=True, source="policy",
                                     evidence_level=E.EvidenceLevel.RESPONSE_ONLY)
    with bind(actor_id="user:ts"):
        service.change_trust(mila, "content.publish_approved", E.TrustLevel.L1,
                             actor="user:ts", reason="QA prolaz")
    return acc


@pytest.fixture
def mailbox(mila):
    acc = ChannelAccount.objects.create(
        persona=mila, channel_type=E.ChannelType.EMAIL, handle="mila@mail.test",
        identity_vehicle=E.IdentityVehicle.NEWSLETTER, status=E.AccountStatus.ACTIVE,
        disclosure_label_status=E.DisclosureLabelStatus.NOT_REQUIRED, credential_ref="vault:m",
    )
    ChannelCapability.objects.create(account=acc, capability="email.outbound_approved",
                                     is_enabled=True, source="policy",
                                     evidence_level=E.EvidenceLevel.RESPONSE_ONLY)
    with bind(actor_id="user:ts"):
        service.change_trust(mila, "email.outbound_approved", E.TrustLevel.L2,
                             actor="user:ts", reason="QA")
    return acc


def _propose(p, at, payload, **kw):
    with bind(actor_id="user:op"):
        return service.propose(Persona.objects.get(pk=p.pk), at, payload, **kw)


