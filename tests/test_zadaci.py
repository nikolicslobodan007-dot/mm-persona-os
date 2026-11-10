"""Stavka 2 — vrste radnih zadataka (registar) i agent_zadatak showcase."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.content import zadaci


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
