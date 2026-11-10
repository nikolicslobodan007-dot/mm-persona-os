"""Stavka 2 — vrste radnih zadataka (registar) i agent_zadatak showcase."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.content import zadaci
from tests.conftest import requires_db


def test_registar_i_nadji():
    z = zadaci.nadji("battlecard")
    assert z.kljuc == "battlecard" and z.naziv
    assert z.upit  # upit za context.build postoji
    # format ubacuje konkretan ulaz bez greške
    assert "HubSpot" in z.uputstvo.format(ulaz="HubSpot")
    assert zadaci.nadji("objava").upit.format(ulaz="AI") == "AI"
    assert set(zadaci.ZADACI) >= {"objava", "battlecard", "outreach", "plan-naloga"}


def test_nepoznata_vrsta():
    with pytest.raises(KeyError):
        zadaci.nadji("nepostoji")


def test_agent_zadatak_actor_mora_user():
    with pytest.raises(CommandError):
        call_command("agent_zadatak", "--vrsta", "battlecard",
                     "--ulaz", "X", "--actor", "service:y")


def test_agent_zadatak_nepoznata_vrsta():
    with pytest.raises(CommandError):
        call_command("agent_zadatak", "--vrsta", "nema", "--ulaz", "X",
                     "--actor", "user:qa")


@requires_db
@pytest.mark.django_db
def test_content_vrsta_pravi_contentitem(mila):
    from api.context import bind
    from apps.content import service, zadaci

    with bind(actor_id="user:qa"):
        clanak = service.draft(mila, topic="AI u B2B prodaji",
                               vrsta=zadaci.nadji("dubinski-clanak"))
    assert clanak.format == "article" and clanak.body

    with bind(actor_id="user:qa"):
        nit = service.draft(mila, topic="Produktivnost u malim timovima",
                            vrsta=zadaci.nadji("nit"))
    assert nit.format == "thread"

    # unazad kompatibilno: bez vrste → kratka objava (POST)
    with bind(actor_id="user:qa"):
        obj = service.draft(mila, topic="Brojke u prodaji")
    assert obj.format == "post"
