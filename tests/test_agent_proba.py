"""agent_proba — brana aktora (ADR-0074: agentski rad vezuje čovek-operator)."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_actor_mora_user():
    with pytest.raises(CommandError):
        call_command("agent_proba", "--tema", "x", "--actor", "service:y")
