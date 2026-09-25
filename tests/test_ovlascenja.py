"""ADR-0037 — šta radno mesto traži i ko sme da da poverenje.

Dve odvojene stvari se ovde brane:

  - **`needs` nije dozvola.** Agent na radnom mestu nema ništa dok mu se ne da;
    motor pravila i dalje gleda samo `TrustState` (ADR-0017).
  - **Niko ne daje ono što sam nema.** Agent kao davalac je ograničen sopstvenim
    nivoom; čovek je koren i bez granice.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from api.context import bind
from apps.personas import ovlascenja
from apps.personas.models import Assignment, Department, Persona, Position
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]


@pytest.fixture
def mesto(db):
    d = Department.objects.create(code="PROBA", name="Proba", sort_order=99)
    return Position.objects.create(
        department=d, code="PRB-PRO", title="Programer probe",
        level=E.OrgLevel.MEDIOR, headcount_max=5,
        needs=["code.read@L0", "code.write@L1:apps/content", "test.run@L0"],
    )


def _zaposli(p, mesto):
    return Assignment.objects.create(persona=p, position=mesto, started_at=timezone.now())


@pytest.fixture
def zaposlen(mila, mesto):
    _zaposli(mila, mesto)
    return mila


@pytest.fixture
def sef(db):
    return Persona.objects.create(
        public_id="P-09100", display_name="Šef", persona_type=E.PersonaType.ASSISTANT,
        status=E.PersonaStatus.ACTIVE,
    )


def _daj(p, cap, nivo, opseg="", actor="user:slobodan"):
    with bind(actor_id=actor):
        return policy.change_trust(p, cap, nivo, actor=actor, reason="proba", scope=opseg)


class TestNeeds:
    def test_oblik_sa_opsegom_i_bez(self, mesto):
        trazi = {(t.capability, t.scope): t.level for t in ovlascenja.needs_of(mesto)}
        assert trazi[("code.read", "")] == E.TrustLevel.L0
        assert trazi[("code.write", "apps/content")] == E.TrustLevel.L1

    def test_recnik_i_string_daju_isto(self, mesto):
        mesto.needs = [{"capability": "code.write", "level": "L1", "scope": "apps/content"}]
        mesto.save(update_fields=["needs"])
        t = ovlascenja.needs_of(mesto)[0]
        assert (t.capability, t.level, t.scope) == ("code.write", E.TrustLevel.L1,
                                                    "apps/content")

    def test_smece_u_needs_se_preskace(self, mesto):
        mesto.needs = ["code.write@L1", "bez-nivoa", 7, {"level": "L1"}, "cap@L9"]
        mesto.save(update_fields=["needs"])
        assert [t.capability for t in ovlascenja.needs_of(mesto)] == ["code.write"]


class TestRadnoMestoNijeDozvola:
    def test_zaposlenje_ne_daje_nista(self, zaposlen):
        """ADR-0017 ostaje: sedenje na mestu ne otvara ništa."""
        assert policy.trust_map(zaposlen) == {}
        assert policy.trust_for(zaposlen, "code.write", "apps/content") == E.TrustLevel.L0

    def test_manjak_je_tacno_ono_sto_fali(self, zaposlen):
        manjak = {(t.capability, t.scope) for t in ovlascenja.gap_for(zaposlen)}
        assert manjak == {("code.write", "apps/content")}   # L0 stavke agent već ima

    def test_dato_nestaje_iz_manjka(self, zaposlen):
        _daj(zaposlen, "code.write", E.TrustLevel.L1, opseg="apps/content")
        assert ovlascenja.gap_for(zaposlen) == []

    def test_zasticena_zona_se_ne_prijavljuje_kao_manjak(self, zaposlen, mesto):
        mesto.needs = ["code.write@L2:apps/policy"]
        mesto.save(update_fields=["needs"])
        assert ovlascenja.gap_for(zaposlen) == []

    def test_agent_bez_mesta_nema_manjka(self, mila):
        assert ovlascenja.gap_for(mila) == []


class TestGranicaDavaoca:
    def test_covek_je_koren(self, mila):
        assert policy.granting_ceiling("user:slobodan", "code.write") is None
        _daj(mila, "code.write", E.TrustLevel.L2)
        assert policy.trust_map(mila)["code.write"] == E.TrustLevel.L2

    def test_agent_ne_daje_iznad_sebe(self, mila, sef):
        _daj(sef, "code.write", E.TrustLevel.L1)
        with pytest.raises(policy.PolicyError) as e:
            _daj(mila, "code.write", E.TrustLevel.L2, actor=f"agent:{sef.public_id}")
        assert e.value.code == "GRANTOR_TOO_LOW"
        assert policy.trust_map(mila) == {}

    def test_agent_daje_do_svog_nivoa(self, mila, sef):
        _daj(sef, "code.write", E.TrustLevel.L1)
        _daj(mila, "code.write", E.TrustLevel.L1, actor=f"agent:{sef.public_id}")
        assert policy.trust_map(mila)["code.write"] == E.TrustLevel.L1

    def test_agent_bez_poverenja_ne_daje_nista(self, mila, sef):
        with pytest.raises(policy.PolicyError) as e:
            _daj(mila, "code.write", E.TrustLevel.L1, actor=f"agent:{sef.public_id}")
        assert e.value.code == "GRANTOR_TOO_LOW"

    def test_agent_ne_podize_sebe(self, sef):
        _daj(sef, "code.write", E.TrustLevel.L1)
        with pytest.raises(policy.PolicyError):
            _daj(sef, "code.write", E.TrustLevel.L2, actor=f"agent:{sef.public_id}")

    def test_granica_se_meri_po_opsegu(self, mila, sef):
        """Šef sa L2 u `apps/content` i L0 drugde ne pravi nikoga izvan svog dela."""
        _daj(sef, "code.write", E.TrustLevel.L2, opseg="apps/content")
        _daj(mila, "code.write", E.TrustLevel.L1, opseg="apps/content",
             actor=f"agent:{sef.public_id}")
        with pytest.raises(policy.PolicyError):
            _daj(mila, "code.write", E.TrustLevel.L1, opseg="apps/channels",
                 actor=f"agent:{sef.public_id}")

    def test_nepostojeci_davalac(self, mila):
        with pytest.raises(policy.PolicyError) as e:
            _daj(mila, "code.write", E.TrustLevel.L1, actor="agent:P-99999")
        assert e.value.code == "UNKNOWN_GRANTOR"


class TestKomanda:
    def test_manjak_ispisuje_i_ne_menja(self, zaposlen):
        out = io.StringIO()
        call_command("poverenje", "--manjak", "--persona", zaposlen.public_id, stdout=out)
        assert "nedostaje" in out.getvalue() and "apps/content" in out.getvalue()
        assert policy.trust_map(zaposlen) == {}

    def test_po_mestu_daje_svima(self, mesto, mila):
        drugi = Persona.objects.create(
            public_id="P-09101", display_name="Drugi",
            persona_type=E.PersonaType.ASSISTANT, status=E.PersonaStatus.ACTIVE)
        _zaposli(mila, mesto)
        _zaposli(drugi, mesto)
        out = io.StringIO()
        call_command("poverenje", "--po-mestu", "PRB-PRO", "--razlog", "prva smena",
                     stdout=out)
        assert "2 dodela kod 2 agenata" in out.getvalue()
        for p in (mila, drugi):
            assert policy.trust_for(p, "code.write", "apps/content") == E.TrustLevel.L1

    def test_po_mestu_ne_daje_iznad_trazenog(self, zaposlen):
        call_command("poverenje", "--po-mestu", "PRB-PRO", "--razlog", "x",
                     stdout=io.StringIO())
        assert policy.trust_for(zaposlen, "code.write", "apps/content") == E.TrustLevel.L1
        assert policy.trust_for(zaposlen, "code.write", "apps/channels") == E.TrustLevel.L0

    def test_ponovljena_dodela_nema_sta_da_da(self, zaposlen):
        call_command("poverenje", "--po-mestu", "PRB-PRO", "--razlog", "x",
                     stdout=io.StringIO())
        out = io.StringIO()
        call_command("poverenje", "--po-mestu", "PRB-PRO", "--razlog", "x", stdout=out)
        assert "nema manjka" in out.getvalue()

    def test_po_mestu_trazi_razlog(self, zaposlen):
        with pytest.raises(CommandError, match="razlog"):
            call_command("poverenje", "--po-mestu", "PRB-PRO", stdout=io.StringIO())

    def test_mesto_bez_needs(self, db):
        d = Department.objects.create(code="PRAZ", name="Prazno", sort_order=98)
        Position.objects.create(department=d, code="PRZ-00", title="Bez zahteva",
                                level=E.OrgLevel.MEDIOR)
        with pytest.raises(CommandError, match="nijednu sposobnost"):
            call_command("poverenje", "--po-mestu", "PRZ-00", "--razlog", "x",
                         stdout=io.StringIO())
