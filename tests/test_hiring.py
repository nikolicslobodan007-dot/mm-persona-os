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
def firma_pre(mila):
    """Stanje kakvo je na serveru: Mila je urednik, mesto šefa je prazno."""
    with bind(actor_id="user:slobodan"):
        call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
    return mila


@pytest.fixture
def firma(firma_pre):
    """Mila je šef marketinga, urednički stolica slobodna za novog agenta."""
    with bind(actor_id="user:slobodan"):
        org.assign(firma_pre, Position.objects.get(code="SEF-MKT"),
                   actor="user:slobodan")
    return firma_pre


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


class TestPremestaj:
    def test_move_frees_the_old_seat(self, firma_pre):
        """Mila ide gore, njeno staro mesto se oslobađa za novog agenta."""
        call_command("premesti", "--persona", "P-00001", "--mesto", "SEF-MKT",
                     stdout=io.StringIO())
        assert org.position_of(firma_pre).code == "SEF-MKT"
        jovan = _zaposli()                       # URE-SR je sada slobodno
        assert org.manager_of(jovan).public_id == "P-00001"
        assert [p.pk for p in org.subordinates(firma_pre)] == [jovan.pk]

    def test_history_is_kept(self, firma_pre):
        from apps.personas.models import Assignment

        call_command("premesti", "--persona", "P-00001", "--mesto", "SEF-MKT",
                     stdout=io.StringIO())
        rasporedi = Assignment.objects.filter(persona=firma_pre).order_by("started_at")
        assert rasporedi.count() == 2
        assert rasporedi.first().ended_at is not None      # staro zatvoreno
        assert rasporedi.last().ended_at is None

    def test_full_seat_is_refused(self, firma_pre):
        """Dok Mila sedi na uredničkom mestu, niko drugi tamo ne može."""
        ana = _zaposli(ime="Ana Perić", mesto="POD-SR")
        with pytest.raises(CommandError, match="popunjeno"):
            call_command("premesti", "--persona", ana.public_id, "--mesto", "URE-SR",
                         stdout=io.StringIO())


class TestDosijeKomanda:
    """ADR-0023 (dopuna) — dosije se popunjava i proverava iz jedne komande."""

    def test_writes_fields_and_bumps_version(self, firma):
        from apps.personas import org

        out = io.StringIO()
        call_command("dosije", "--persona", "P-00001", "--visina", "170",
                     "--gradja", "vitka", "--oci", "tamne",
                     "--hobiji", "trčanje, keramika", stdout=out)
        d = org.dossier_of(firma)
        assert (d.height_cm, d.build, d.eye_color) == (170, "vitka", "tamne")
        assert d.hobbies == ["trčanje", "keramika"]

    def test_show_prints_the_image_text(self, firma):
        call_command("dosije", "--persona", "P-00001",
                     "--izgled", "Žena u tridesetim, vitka, tamna kosa do ramena.",
                     stdout=io.StringIO())
        out = io.StringIO()
        call_command("dosije", "--persona", "P-00001", "--pokazi", stdout=out)
        tekst = out.getvalue()
        assert "tekst za sliku" in tekst
        assert "Žena u tridesetim" in tekst
        assert "Radi kao" in tekst            # radno mesto se dodaje samo

    def test_forbidden_description_is_refused(self, firma):
        with pytest.raises(CommandError, match="odbijen"):
            call_command("dosije", "--persona", "P-00001",
                         "--izgled", "Lice poznatog glumca, sa logotipom Nike na majici.",
                         stdout=io.StringIO())

    def test_unknown_persona(self, firma):
        with pytest.raises(CommandError, match="ne postoji"):
            call_command("dosije", "--persona", "P-09999", "--pokazi",
                         stdout=io.StringIO())
