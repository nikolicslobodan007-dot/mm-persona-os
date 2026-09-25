"""ADR-0042 — merenje rada po agentu.

Dve tvrdnje koje se ovde brane, i obe su o poštenju brojeva:

  - **„prošla iz prvog puta" znači prvi pokušaj**, ne poslednji. Posle popravke
    svako prođe; razlika između prvog i trećeg je jedino što nešto govori.
  - **ono što nema izvor ostaje `None`**, ne nula. Nula tvrdi da je izmereno i da
    je ispalo nula — a to je laž o trošku koji nikad nije meren (ADR-0033).
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command

from api.context import bind
from apps.orchestration import ucinak as U
from apps.orchestration import zadaci, zakrpa
from apps.personas.models import Persona
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

DIFF = ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
        "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n@@ -1 +1 @@\n-a\n+b\n")
ZONA = ("diff --git a/apps/policy/service.py b/apps/policy/service.py\n"
        "--- a/apps/policy/service.py\n+++ b/apps/policy/service.py\n@@ -1 +1 @@\n-a\n+b\n")


@pytest.fixture
def recenzent(db):
    return Persona.objects.create(
        public_id="P-09300", display_name="Recenzent",
        persona_type=E.PersonaType.ASSISTANT, status=E.PersonaStatus.ACTIVE)


@pytest.fixture
def z(mila):
    with bind(actor_id="user:slobodan"):
        policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                            actor="user:slobodan", reason="p", scope="apps/content")
        return zadaci.create(title="Merenje", why="Provera učinka.",
                             allowed_paths=["apps/content"], assignee=mila)


class TestOsnovno:
    def test_prazan_agent(self, mila):
        r = U.za_agenta(mila)
        assert r.zadataka == 0 and r.zakrpa == 0
        assert r.iz_prvog_puta is None and r.zakrpa_prihvaceno is None

    def test_broji_zadatke_i_zavrsene(self, z, mila):
        assert U.za_agenta(mila).zadataka == 1
        assert U.za_agenta(mila).zavrsenih == 0
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)
            zadaci.finish(z)
        assert U.za_agenta(mila).zavrsenih == 1

    def test_broji_zakrpe(self, z, mila):
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, DIFF, persona=mila)
            zakrpa.submit(z, ZONA, persona=mila)
        r = U.za_agenta(mila)
        assert (r.zakrpa, r.prihvacenih, r.odbijenih) == (2, 1, 1)
        assert r.zakrpa_prihvaceno == 0.5

    def test_pokusaj_u_zonu_se_vidi(self, z, mila):
        """Agent koji stalno gura u zaštićenu zonu vidi se samo ovde."""
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, ZONA, persona=mila)
        assert U.za_agenta(mila).odbijenih_zbog_zone == 1


class TestIzPrvogPuta:
    def test_zelena_iz_prvog(self, z, mila):
        with bind(actor_id="user:slobodan"):
            zadaci.record_gate(z, "pytest", True)
        r = U.za_agenta(mila)
        assert (r.kapija_mereno, r.kapija_iz_prvog) == (1, 1)
        assert r.iz_prvog_puta == 1.0

    def test_popravka_ne_prepravlja_istoriju(self, z, mila):
        """Pala pa popravljena kapija ostaje „nije iz prvog puta"."""
        with bind(actor_id="user:slobodan"):
            zadaci.record_gate(z, "pytest", False)
            zadaci.record_gate(z, "pytest", True)
        r = U.za_agenta(mila)
        assert r.kapija_mereno == 1 and r.kapija_iz_prvog == 0
        assert r.iz_prvog_puta == 0.0

    def test_mesano(self, z, mila):
        with bind(actor_id="user:slobodan"):
            zadaci.record_gate(z, "pytest", False)
            zadaci.record_gate(z, "pytest", True)
            zadaci.record_gate(z, "ruff", True)
            zadaci.record_gate(z, "canon_lint", True)
            zadaci.record_gate(z, "migrations", True)
        assert U.za_agenta(mila).iz_prvog_puta == 0.75

    def test_dve_zakrpe_se_broje_odvojeno(self, z, mila):
        """Nova zakrpa je nov posao — njene kapije su svoje merenje (ADR-0040)."""
        with bind(actor_id="user:slobodan"):
            p1 = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", False, patch=p1)
            p2 = zakrpa.submit(z, DIFF.replace("+b", "+c"), persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=p2)
        r = U.za_agenta(mila)
        assert r.kapija_mereno == 2 and r.kapija_iz_prvog == 1


class TestNalazi:
    def test_broji_nalaze_na_njegov_rad(self, z, mila, recenzent):
        with bind(actor_id="user:slobodan"):
            zadaci.add_finding(z, reviewer=recenzent, file="apps/content/x.py",
                               claim="puca na praznom", severity="BLOCKER")
            zadaci.add_finding(z, reviewer=recenzent, file="apps/content/x.py",
                               claim="ime promenljive", severity="NIT")
        r = U.za_agenta(mila)
        assert r.nalaza_na_rad == 2 and r.blokera_na_rad == 1


class TestSteNeMeri:
    def test_trosak_je_none_a_ne_nula(self, z, mila):
        """Nula bi tvrdila da je mereno i ispalo nula. Nije mereno."""
        assert U.za_agenta(mila).trosak_centi is None

    def test_spisak_neizmerenog_ide_uz_rezultat(self, mila):
        r = U.za_agenta(mila)
        assert r.ne_meri_se and any("trošak" in s for s in r.ne_meri_se)
        assert any("vraćene" in s for s in r.ne_meri_se)


class TestKomanda:
    def test_ispis_i_upozorenje(self, z, mila, recenzent):
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, ZONA, persona=mila)
            zadaci.add_finding(z, reviewer=recenzent, file="apps/content/x.py",
                               claim="puca", severity="BLOCKER")
        out = io.StringIO()
        call_command("ucinak", stdout=out)
        ispis = out.getvalue()
        assert mila.public_id in ispis
        assert "BLOCKER" in ispis
        assert "Šta se NE meri" in ispis

    def test_po_agentu(self, z, mila):
        out = io.StringIO()
        call_command("ucinak", "--persona", mila.public_id, stdout=out)
        assert mila.public_id in out.getvalue()

    def test_nepoznata_persona(self, db):
        with pytest.raises(CommandError, match="ne postoji"):
            call_command("ucinak", "--persona", "P-99999", stdout=io.StringIO())

    def test_prazno_stanje(self, db):
        out = io.StringIO()
        call_command("ucinak", stdout=out)
        assert "Nema nijednog agenta" in out.getvalue()
