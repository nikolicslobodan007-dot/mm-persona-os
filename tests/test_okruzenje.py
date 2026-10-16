"""ADR-0100 — prelazak agenta u živo okruženje ima svoj put.

Šta se ovde brani:

  - u živo se ide samo kroz ovu komandu, uz **čoveka** i uz **razlog**;
  - svaki prelazak ostaje u auditu, sa „iz čega u šta" i „zašto";
  - u živo ne ide agent koji nije READY ili ACTIVE;
  - nazad u simulaciju ide uvek — stezanje nije teže od popuštanja;
  - ista vrednost nije događaj i ne upisuje se.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command

from apps.observability.models import AuditEvent
from apps.personas.models import Persona
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

DOGADJAJ = "persona.environment.changed"
RAZLOG = "čita javne izvore za nalaze"


def _pozovi(**kw):
    call_command("okruzenje", stdout=io.StringIO(), **kw)


def _u_statusu(p, status):
    Persona.objects.filter(pk=p.pk).update(status=status)
    return Persona.objects.get(pk=p.pk)


@pytest.mark.django_db
class TestOkruzenje:
    def test_u_zivo_uz_coveka_i_razlog(self, mila):
        _u_statusu(mila, E.PersonaStatus.READY.value)
        _pozovi(persona=mila.public_id, na=E.RuntimeEnvironment.CONTROLLED_LIVE.value,
                razlog=RAZLOG, actor="user:slobodan")
        p = Persona.objects.get(pk=mila.pk)
        assert p.runtime_environment == E.RuntimeEnvironment.CONTROLLED_LIVE.value

        ev = AuditEvent.objects.filter(event_key=DOGADJAJ).latest("occurred_at")
        assert ev.payload["details"]["razlog"] == RAZLOG
        assert ev.payload["declared_actor"] == "user:slobodan"
        # `before`/`after` audit čuva samo kao otisak (api/audit.py), pa se
        # „iz čega u šta" čita iz `details` — tamo i mora da stoji.
        assert ev.payload["details"]["iz"] == "SIMULATION"
        assert ev.payload["details"]["u"] == "CONTROLLED_LIVE"
        assert ev.payload["before_hash"] and ev.payload["after_hash"]

    def test_bez_razloga_se_odbija(self, mila):
        _u_statusu(mila, E.PersonaStatus.READY.value)
        with pytest.raises(CommandError, match="razlog"):
            _pozovi(persona=mila.public_id,
                    na=E.RuntimeEnvironment.CONTROLLED_LIVE.value,
                    razlog="   ", actor="user:slobodan")
        assert Persona.objects.get(pk=mila.pk).runtime_environment == "SIMULATION"

    def test_agent_ne_pusta_sam_sebe(self, mila):
        _u_statusu(mila, E.PersonaStatus.READY.value)
        with pytest.raises(CommandError, match="čovek"):
            _pozovi(persona=mila.public_id,
                    na=E.RuntimeEnvironment.CONTROLLED_LIVE.value,
                    razlog=RAZLOG, actor="agent:P-00001")
        assert Persona.objects.get(pk=mila.pk).runtime_environment == "SIMULATION"

    def test_nacrt_persone_ne_ide_u_zivo(self, mila):
        _u_statusu(mila, E.PersonaStatus.DRAFT.value)
        with pytest.raises(CommandError, match="DRAFT"):
            _pozovi(persona=mila.public_id,
                    na=E.RuntimeEnvironment.CONTROLLED_LIVE.value,
                    razlog=RAZLOG, actor="user:slobodan")
        assert Persona.objects.get(pk=mila.pk).runtime_environment == "SIMULATION"

    def test_nazad_u_simulaciju_ide_uvek(self, mila):
        """Stezanje ne sme da bude teže od popuštanja — ni za SUSPENDED agenta."""
        Persona.objects.filter(pk=mila.pk).update(
            runtime_environment=E.RuntimeEnvironment.CONTROLLED_LIVE.value,
            status=E.PersonaStatus.SUSPENDED.value)
        _pozovi(persona=mila.public_id, na=E.RuntimeEnvironment.SIMULATION.value,
                razlog="povlačim dok ne proverim", actor="user:slobodan")
        assert Persona.objects.get(pk=mila.pk).runtime_environment == "SIMULATION"

    def test_ista_vrednost_nije_dogadjaj(self, mila):
        pre = AuditEvent.objects.filter(event_key=DOGADJAJ).count()
        _pozovi(persona=mila.public_id, na=E.RuntimeEnvironment.SIMULATION.value,
                razlog="ponovljena komanda", actor="user:slobodan")
        assert AuditEvent.objects.filter(event_key=DOGADJAJ).count() == pre

    def test_okruzenje_samo_po_sebi_ne_daje_dozvolu(self, mila):
        """ADR-0100 — živo okruženje uklanja jedan uslov, ne dodaje nijedno pravo."""
        from apps.policy import service

        _u_statusu(mila, E.PersonaStatus.READY.value)
        pre = service.trust_map(mila)
        _pozovi(persona=mila.public_id, na=E.RuntimeEnvironment.CONTROLLED_LIVE.value,
                razlog=RAZLOG, actor="user:slobodan")
        assert service.trust_map(Persona.objects.get(pk=mila.pk)) == pre
