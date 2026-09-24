"""ADR-0023 — zapošljavanje agenta.

  - jedna komanda pravi agenta od praznog do `READY`;
  - agent dobija sve što mu scheduler traži (stanje, rutina), ali **nijednu dozvolu**;
  - radno mesto i šef dolaze iz organizacije, ne iz komande;
  - dva agenta nisu isti čovek, a isti ID uvek daje iste osobine;
  - ime bez prezimena, zauzet slug i nepostojeće radno mesto se odbijaju.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command

from api.context import bind
from apps.behaviour.models import BehaviourState, RoutineTemplate
from apps.personas import hiring, org
from apps.personas.models import Persona, Position
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]


@pytest.fixture
def firma(mila):
    with bind(actor_id="user:slobodan"):
        call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
        org.assign(mila, Position.objects.get(code="SEF-MKT"), actor="user:slobodan")
    return mila


def _zaposli(ime="Jovan Ilić", mesto="URE-SR", **kw) -> Persona:
    out = io.StringIO()
    call_command("zaposli", "--ime", ime, "--mesto", mesto, stdout=out, **kw)
    return Persona.objects.get(slug=hiring.slugify_sr(ime))


class TestZaposljavanje:
    def test_agent_is_ready_and_seated(self, firma):
        p = _zaposli()
        assert p.public_id == "P-00002"
        assert p.display_name == "Jovan Ilić (AI)"          # oznaka je u imenu
        assert p.status == E.PersonaStatus.READY
        assert p.runtime_environment == E.RuntimeEnvironment.SIMULATION
        assert org.position_of(p).code == "URE-SR"
        assert org.manager_of(p).public_id == "P-00001"     # odgovara Mili

    def test_scheduler_has_everything_it_needs(self, firma):
        p = _zaposli()
        assert BehaviourState.objects.filter(persona=p).exists()
        assert RoutineTemplate.objects.filter(persona=p, is_enabled=True).count() == 2
        assert p.biography.occupation_title.startswith("Urednik sadržaja")
        assert "kao ljudsko biće" in p.voice_profile.banned_phrases

    def test_new_agent_has_no_permission(self, firma):
        """Radno mesto ne daje nijednu dozvolu (ADR-0017)."""
        from apps.policy.models import TrustState

        p = _zaposli()
        assert p.trust_level == E.TrustLevel.L0
        assert not TrustState.objects.filter(persona=p).exclude(
            level=E.TrustLevel.L0.value).exists()
        assert not p.channel_accounts.exclude(
            channel_type=E.ChannelType.SANDBOX.value).exists()

    def test_two_agents_differ_but_one_id_is_stable(self, firma):
        p1 = _zaposli()
        p2 = _zaposli(ime="Ana Perić", mesto="POD-SR")
        assert p1.trait_profile.openness != p2.trait_profile.openness
        assert hiring._traits_for("P-00007") == hiring._traits_for("P-00007")

    def test_dossier_from_the_same_command(self, firma):
        p = _zaposli(ime="Ana Perić", mesto="POD-SR",
                     rodjen="Niš", zivi="Beograd", visina=168)
        d = org.dossier_of(p)
        assert (d.birth_place, d.residence, d.height_cm) == ("Niš", "Beograd", 168)


class TestOdbijanje:
    def test_unknown_position(self, firma):
        with pytest.raises(CommandError, match="ne postoji"):
            _zaposli(mesto="NEMA-GA")

    def test_name_without_surname(self, firma):
        with pytest.raises(CommandError, match="ime i prezime"):
            _zaposli(ime="Jovan")

    def test_taken_slug(self, firma):
        _zaposli()
        with pytest.raises(CommandError, match="zauzet"):
            _zaposli()

    def test_minor_is_refused(self, firma):
        with pytest.raises(CommandError, match="odrasla"):
            _zaposli(ime="Ana Perić", mesto="POD-SR", **{"dob": "2015-01-01"})
