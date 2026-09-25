"""ADR-0043 — rezultat rada ide u granu, ne u `main`.

Četiri tvrdnje koje se ovde brane:

  - **grana se otvara samo nad zelenim kapijama TE zakrpe.** Zeleno nad starijom
    zakrpom ne znači ništa o novoj (ADR-0040);
  - **agentov tekst ne izlazi iz teksta.** Naslov zadatka piše agent; ako prelom
    reda ili `<` prođu kroz potpis, agent sam sebi bira ime autora;
  - **grana se pomera samo sa onoga što aplikacija zna** — otud `commit_sha` kao
    očekivana vrednost za `--force-with-lease`;
  - **zadatak se ovde ne zatvara.** Grana je ponuda na sto (ADR-0038 §6).
"""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command

from api.context import bind
from apps.orchestration import rezultat, zadaci, zakrpa
from apps.orchestration.models import CodeTask
from apps.personas.models import Persona
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

SHA = "a" * 40
DRUGI_SHA = "b" * 40
DIFF = ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
        "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n@@ -1 +1 @@\n-a\n+b\n")


@pytest.fixture
def z(mila):
    with bind(actor_id="user:slobodan"):
        policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                            actor="user:slobodan", reason="p", scope="apps/content")
        return zadaci.create(title="Grana", why="Provera rezultata.", adr="ADR-0043",
                             allowed_paths=["apps/content"], assignee=mila)


@pytest.fixture
def zk(z, mila):
    with bind(actor_id="user:slobodan"):
        return zakrpa.submit(z, DIFF, persona=mila)


def zeleno(z, zk, *, osim: str = "") -> None:
    with bind(actor_id="user:slobodan"):
        for g in z.required_gates:
            if g != osim:
                zadaci.record_gate(z, g, True, patch=zk)


class TestImeIPotpis:
    def test_grana_nosi_identifikator(self, z):
        assert rezultat.ime_grane(z) == f"zadatak/{z.public_id}"

    def test_grana_odbija_neispravan_id(self, db):
        lazni = CodeTask(public_id="TSK-neispravno")
        with pytest.raises(zadaci.TaskError, match="Neispravan identifikator"):
            rezultat.ime_grane(lazni)

    def test_adresa_je_po_agentu(self, mila):
        ime, mejl = rezultat.potpis(mila)
        assert mejl == f"{mila.public_id.lower()}@{rezultat.DOMEN_AGENATA}"
        assert ime == mila.display_name

    def test_bez_izvrsioca_nema_potpisa(self, db):
        with pytest.raises(zadaci.TaskError, match="nema izvršioca"):
            rezultat.potpis(None)

    def test_ime_gubi_uglaste_zagrade_i_prelome(self, db):
        opak = Persona.objects.create(
            public_id="P-09301", display_name="Zli <root@host>\nFrom: neko",
            persona_type=E.PersonaType.ASSISTANT, status=E.PersonaStatus.ACTIVE)
        ime, _ = rezultat.potpis(opak)
        assert "<" not in ime and ">" not in ime and "\n" not in ime


class TestPoruka:
    def test_nosi_zadatak_zakrpu_i_agenta(self, z, zk, mila):
        p = rezultat.poruka(z, zk)
        assert p.startswith(f"{z.public_id}: Grana")
        assert str(zk.pk) in p and mila.public_id in p and "ADR-0043" in p
        assert "ljudskom rukom" in p

    def test_naslov_sa_prelomom_ostaje_jedan_red(self, z, zk):
        z.title = "Prvi red\nSubject: lažni"
        p = rezultat.poruka(z, zk)
        assert p.split("\n")[0] == f"{z.public_id}: Prvi red Subject: lažni"

    def test_zavrsava_se_prelomom(self, z, zk):
        assert rezultat.poruka(z, zk).endswith("\n")


class TestPriprema:
    def test_prazna_ocekivana_vrednost_kad_grane_nema(self, z, zk):
        assert rezultat.priprema(z, zk)["branch_expected_sha"] == ""

    def test_ocekivana_vrednost_je_zapisani_commit(self, z, zk):
        zeleno(z, zk)
        with bind(actor_id="service:runner"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)
        z.refresh_from_db()
        assert rezultat.priprema(z, zk)["branch_expected_sha"] == SHA


class TestZabelezi:
    def test_zeleno_otvara_granu(self, z, zk):
        zeleno(z, zk)
        with bind(actor_id="service:runner"):
            out = rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)
        z.refresh_from_db()
        assert out.applied_sha == SHA
        assert out.status == E.PatchStatus.APPLIED.value
        assert z.commit_sha == SHA

    def test_ne_zatvara_zadatak(self, z, zk):
        """Grana je ponuda na sto, ne odluka (ADR-0038 §6)."""
        zeleno(z, zk)
        with bind(actor_id="service:runner"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)
        z.refresh_from_db()
        assert z.status != E.TaskStatus.DONE.value
        assert z.finished_at is None

    def test_pala_kapija_ne_otvara_granu(self, z, zk):
        zeleno(z, zk, osim="pytest")
        with bind(actor_id="user:slobodan"):
            zadaci.record_gate(z, "pytest", False, patch=zk)
        with pytest.raises(zadaci.TaskError, match="pala"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)

    def test_nevrtena_kapija_ne_otvara_granu(self, z, zk):
        zeleno(z, zk, osim="ruff")
        with pytest.raises(zadaci.TaskError, match="nije vrtena"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)

    def test_zeleno_nad_starijom_zakrpom_ne_vazi(self, z, zk, mila):
        """Kapije se mere po zakrpi. Tuđe zeleno nije ovo zeleno (ADR-0040)."""
        zeleno(z, zk)
        with bind(actor_id="user:slobodan"):
            nova = zakrpa.submit(z, DIFF.replace("+b", "+c"), persona=mila)
        with pytest.raises(zadaci.TaskError, match="nije vrtena"):
            rezultat.zabelezi(z, nova, branch=rezultat.ime_grane(z), commit_sha=SHA)

    def test_otvoren_blocker_zadrzava(self, z, zk, mila):
        zeleno(z, zk)
        recenzent = Persona.objects.create(
            public_id="P-09302", display_name="Recenzent",
            persona_type=E.PersonaType.ASSISTANT, status=E.PersonaStatus.ACTIVE)
        with bind(actor_id="user:slobodan"):
            zadaci.add_finding(z, reviewer=recenzent, file="apps/content/x.py",
                               claim="puca", severity="BLOCKER")
        with pytest.raises(zadaci.TaskError, match="BLOCKER"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)

    @pytest.mark.parametrize("los", ["", "nije sha", "g" * 40, "a" * 39, "a" * 41])
    def test_odbija_los_commit(self, z, zk, los):
        zeleno(z, zk)
        with pytest.raises(zadaci.TaskError, match="heksadecimalnih"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=los)

    def test_veliko_slovo_u_sha_se_svodi_na_malo(self, z, zk):
        zeleno(z, zk)
        with bind(actor_id="service:runner"):
            out = rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z),
                                    commit_sha="ABCDEF" + "0" * 34)
        assert out.applied_sha == "abcdef" + "0" * 34

    def test_odbija_tudju_granu(self, z, zk):
        zeleno(z, zk)
        with pytest.raises(zadaci.TaskError, match="Grana mora biti"):
            rezultat.zabelezi(z, zk, branch="main", commit_sha=SHA)

    def test_odbija_zakrpu_drugog_zadatka(self, z, zk, mila):
        zeleno(z, zk)
        with bind(actor_id="user:slobodan"):
            drugi = zadaci.create(title="Drugi", why="Drugi razlog.",
                                  allowed_paths=["apps/content"], assignee=mila)
        with pytest.raises(zadaci.TaskError, match="ne pripada"):
            rezultat.zabelezi(drugi, zk, branch=rezultat.ime_grane(drugi),
                              commit_sha=SHA)

    def test_odbijena_zakrpa_ne_ide_u_granu(self, z, mila):
        with bind(actor_id="user:slobodan"):
            odbijena = zakrpa.submit(
                z, DIFF.replace("apps/content/x.py", "apps/policy/service.py"),
                persona=mila)
            for g in z.required_gates:
                zadaci.record_gate(z, g, True, patch=odbijena)
        with pytest.raises(zadaci.TaskError, match="prihvaćena"):
            rezultat.zabelezi(z, odbijena, branch=rezultat.ime_grane(z), commit_sha=SHA)

    def test_isti_commit_dvaput_je_uredan_ishod(self, z, zk):
        zeleno(z, zk)
        with bind(actor_id="service:runner"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)
            out = rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)
        assert out.applied_sha == SHA

    def test_drugi_commit_nad_istom_zakrpom_je_sukob(self, z, zk):
        zeleno(z, zk)
        with bind(actor_id="service:runner"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)
        with pytest.raises(zadaci.TaskError, match="već ima commit"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=DRUGI_SHA)


class TestUcinakVidiGranu:
    def test_primenjena_zakrpa_ostaje_prihvacena(self, z, zk, mila):
        """`APPLIED` je uspeh; mera ne sme da ga broji kao gubitak prihvaćene."""
        from apps.orchestration import ucinak

        zeleno(z, zk)
        with bind(actor_id="service:runner"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)
        r = ucinak.za_agenta(mila)
        assert r.prihvacenih == 1 and r.u_grani == 1
        assert r.zakrpa_prihvaceno == 1.0


class TestKomandaGrane:
    def test_prazno_stanje(self, db):
        out = io.StringIO()
        call_command("grane", stdout=out)
        assert "Nijedna grana" in out.getvalue()

    def test_ispisuje_granu_i_komandu_za_dovlacenje(self, z, zk):
        zeleno(z, zk)
        with bind(actor_id="service:runner"):
            rezultat.zabelezi(z, zk, branch=rezultat.ime_grane(z), commit_sha=SHA)
        out = io.StringIO()
        call_command("grane", stdout=out)
        ispis = out.getvalue()
        assert f"zadatak/{z.public_id}" in ispis
        assert "git fetch" in ispis
        assert "ne na serveru" in ispis
