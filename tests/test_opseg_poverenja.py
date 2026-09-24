"""ADR-0034 — poverenje po opsegu i zaštićene zone.

  - isti agent je `L1` u jednom delu koda i `L0` u drugom;
  - najduži opseg pobeđuje, pa uže pravilo obara šire u oba smera;
  - zaštićena zona se ne otvara ni na jednom nivou — ni komandom ni kodom;
  - stari put (poverenje bez opsega) radi kao i pre.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command

from api.context import bind
from apps.policy import service
from apps.policy.models import TrustState
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]


def _daj(p, cap, nivo, opseg="", razlog="proba"):
    with bind(actor_id="user:slobodan"):
        return service.change_trust(p, cap, nivo, actor="user:slobodan",
                                    reason=razlog, scope=opseg)


class TestOpseg:
    def test_isti_agent_dva_nivoa(self, mila):
        _daj(mila, "code.write", E.TrustLevel.L1)
        _daj(mila, "code.write", E.TrustLevel.L0, opseg="apps/content")
        assert service.trust_for(mila, "code.write", "apps/channels/mailbox.py") \
            == E.TrustLevel.L1
        assert service.trust_for(mila, "code.write", "apps/content/steps.py") \
            == E.TrustLevel.L0

    def test_najduzi_opseg_pobedjuje(self, mila):
        _daj(mila, "code.write", E.TrustLevel.L0)
        _daj(mila, "code.write", E.TrustLevel.L1, opseg="apps")
        _daj(mila, "code.write", E.TrustLevel.L2, opseg="apps/content/steps.py")
        assert service.trust_for(mila, "code.write", "README.md") == E.TrustLevel.L0
        assert service.trust_for(mila, "code.write", "apps/memory/writer.py") \
            == E.TrustLevel.L1
        assert service.trust_for(mila, "code.write", "apps/content/steps.py") \
            == E.TrustLevel.L2

    def test_bez_ijednog_zapisa_je_L0(self, mila):
        assert service.trust_for(mila, "code.write", "apps/content/steps.py") \
            == E.TrustLevel.L0

    def test_opseg_ne_curi_u_opstu_mapu(self, mila):
        """Motor pravila dobija samo poverenje bez opsega — inače bi uži red
        tiho menjao odluke svuda, a ne samo u svom delu koda."""
        _daj(mila, "code.write", E.TrustLevel.L2, opseg="apps/content")
        assert "code.write" not in service.trust_map(mila)
        _daj(mila, "code.write", E.TrustLevel.L1)
        assert service.trust_map(mila)["code.write"] == E.TrustLevel.L1

    def test_kose_crte_i_tacka_ne_menjaju_ishod(self, mila):
        _daj(mila, "code.write", E.TrustLevel.L1, opseg="apps/content")
        for putanja in ("apps/content/steps.py", "./apps/content/steps.py",
                        "apps\\content\\steps.py"):
            assert service.trust_for(mila, "code.write", putanja) == E.TrustLevel.L1


class TestZasticeneZone:
    @pytest.mark.parametrize("putanja", [
        "apps/policy/service.py", "api/audit.py", "apps/runtime/transport.py",
        "common/enums.py", "docs/adr/0001-canon-v1.md", "tools/canon_lint.py",
        "policy/capabilities.yaml",
    ])
    def test_zona_je_zabranjena(self, putanja):
        assert service.path_is_protected(putanja) is not None

    @pytest.mark.parametrize("putanja", [
        "apps/content/steps.py", "apps/channels/mailbox.py", "console/views.py",
        "tests/test_org.py", "apps/policyx/nesto.py",
    ])
    def test_ostalo_nije(self, putanja):
        assert service.path_is_protected(putanja) is None

    def test_poverenje_se_ne_dodeljuje_na_zonu(self, mila):
        with pytest.raises(service.PolicyError) as e:
            _daj(mila, "code.write", E.TrustLevel.L2, opseg="apps/policy")
        assert e.value.code == "PROTECTED_PATH"
        assert not TrustState.objects.filter(persona=mila, scope="apps/policy").exists()

    def test_nivo_ne_otvara_zonu(self, mila):
        """Ni najviši dodeljiv nivo ne pomaže: zona se ne proverava nivoom."""
        _daj(mila, "code.write", E.TrustLevel.L2)
        assert service.trust_for(mila, "code.write", "apps/policy/service.py") \
            == E.TrustLevel.L2          # poverenje jeste visoko…
        assert service.path_is_protected("apps/policy/service.py")  # …ali zona stoji


class TestKomanda:
    def test_dodela_i_ispis(self, mila):
        out = io.StringIO()
        call_command("poverenje", "--persona", "P-00001", "--sposobnost", "code.write",
                     "--opseg", "apps/content", "--nivo", "L1", "--razlog", "prvi zadatak",
                     stdout=out)
        assert "apps/content" in out.getvalue() and "L1" in out.getvalue()
        out = io.StringIO()
        call_command("poverenje", "--persona", "P-00001", stdout=out)
        assert "code.write" in out.getvalue()

    def test_zona_se_odbija_iz_komande(self, mila):
        with pytest.raises(CommandError, match="zaštićena zona"):
            call_command("poverenje", "--persona", "P-00001", "--sposobnost", "code.write",
                         "--opseg", "apps/policy", "--nivo", "L1", "--razlog", "ne može",
                         stdout=io.StringIO())

    def test_bez_razloga_se_odbija(self, mila):
        with pytest.raises(CommandError, match="razlog"):
            call_command("poverenje", "--persona", "P-00001", "--sposobnost", "code.write",
                         "--nivo", "L1", stdout=io.StringIO())

    def test_provera_putanje(self, mila):
        out = io.StringIO()
        call_command("poverenje", "--proveri", "apps/runtime/transport.py", stdout=out)
        assert "zaštićena zona" in out.getvalue()

    def test_spisak_zona(self):
        out = io.StringIO()
        call_command("poverenje", "--zone", stdout=out)
        assert "apps/policy/" in out.getvalue() and "common/enums.py" in out.getvalue()
