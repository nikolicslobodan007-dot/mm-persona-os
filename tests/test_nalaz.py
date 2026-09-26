"""ADR-0045 — nalaz koji piše čovek, i pravilo koje ga čuva.

Dve tvrdnje:

  - **`BLOCKER` postavlja samo čovek.** Do sada je to pravilo živelo jedino kao
    tabela preslikavanja u uvozniku SARIF-a — dakle kao nešto što se zaobilazi
    time što se doda drugi put do `add_finding`. Sada stoji u servisu.
  - **Izvršilac ne zatvara nalaz na sopstveni rad.** Agent koji ne sme da odobri
    svoj kod ne sme ni da skloni prigovor na njega, inače je `BLOCKER` ukras.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command

from api.context import bind
from apps.orchestration import rezultat, zadaci, zakrpa
from apps.orchestration.models import ReviewFinding
from apps.personas.models import Persona
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

DIFF = ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
        "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n@@ -1 +1 @@\n-a\n+b\n")


@pytest.fixture
def z(mila):
    with bind(actor_id="user:slobodan"):
        policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                            actor="user:slobodan", reason="p", scope="apps/content")
        return zadaci.create(title="Nalaz", why="Provera ljudskog nalaza.",
                             allowed_paths=["apps/content"], assignee=mila)


def _upisi(z, tezina="BLOCKER", fajl="apps/content/lessons.py", tvrdnja="Ćuti o sečenju."):
    with bind(actor_id="user:slobodan"):
        return zadaci.add_finding(z, reviewer=None, file=fajl, claim=tvrdnja,
                                  severity=tezina, line=131,
                                  source=zadaci.IZVOR_COVEK)


class TestSamoCovekDajeBlocker:
    def test_covek_sme(self, z):
        n = _upisi(z)
        assert n.severity == "BLOCKER" and n.source == zadaci.IZVOR_COVEK

    @pytest.mark.parametrize("izvor", ["agent", "open-code-review", "ruff", ""])
    def test_masina_ne_sme(self, z, izvor):
        with bind(actor_id="user:slobodan"), \
             pytest.raises(zadaci.TaskError, match="samo čovek"):
            zadaci.add_finding(z, reviewer=None, file="apps/content/x.py",
                               claim="puca", severity="BLOCKER", source=izvor)

    def test_masina_sme_nize_tezine(self, z):
        with bind(actor_id="user:slobodan"):
            n = zadaci.add_finding(z, reviewer=None, file="apps/content/x.py",
                                   claim="ime promenljive", severity="MAJOR",
                                   source="open-code-review")
        assert n.severity == "MAJOR"

    def test_sarif_uvoz_i_dalje_ne_moze_do_blockera(self, z):
        """ADR-0036 §2 — preslikavanje je stepen niže; sada i servis to drži."""
        from apps.orchestration import recenzija

        assert E.FindingSeverity.BLOCKER.value not in recenzija.SARIF_TO_SEVERITY.values()


class TestZatvaranje:
    def test_covek_zatvara(self, z):
        n = _upisi(z)
        with bind(actor_id="user:slobodan"):
            zadaci.close_finding(n, "FIXED", actor="user:slobodan")
        n.refresh_from_db()
        assert n.status == "FIXED"

    def test_izvrsilac_ne_zatvara_svoj(self, z, mila):
        n = _upisi(z)
        with bind(actor_id=f"agent:{mila.public_id}"), \
             pytest.raises(zadaci.TaskError, match="sopstveni rad"):
            zadaci.close_finding(n, "FIXED", actor=f"agent:{mila.public_id}")

    def test_drugi_agent_sme(self, z, mila):
        n = _upisi(z)
        with bind(actor_id="agent:P-09999"):
            zadaci.close_finding(n, "REJECTED", actor="agent:P-09999")
        n.refresh_from_db()
        assert n.status == "REJECTED"

    def test_open_nije_zatvaranje(self, z):
        n = _upisi(z)
        with pytest.raises(zadaci.TaskError, match="nije zatvaranje"):
            zadaci.close_finding(n, "OPEN", actor="user:slobodan")

    def test_nepoznat_status(self, z):
        n = _upisi(z)
        with pytest.raises(zadaci.TaskError, match="Nepoznat status"):
            zadaci.close_finding(n, "SREDJENO", actor="user:slobodan")


class TestBlockerStvarnoZaustavlja:
    def test_zadatak_se_ne_zatvara(self, z):
        _upisi(z)
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)
            with pytest.raises(zadaci.TaskError, match="BLOCKER"):
                zadaci.finish(z)

    def test_grana_se_ne_otvara(self, z, mila):
        _upisi(z)
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, DIFF, persona=mila)
            for g in z.required_gates:
                zadaci.record_gate(z, g, True, patch=p)
            with pytest.raises(zadaci.TaskError, match="BLOCKER"):
                rezultat.zabelezi(z, p, branch=rezultat.ime_grane(z), commit_sha="a" * 40)

    def test_zatvoren_nalaz_pusta_dalje(self, z):
        n = _upisi(z)
        with bind(actor_id="user:slobodan"):
            zadaci.close_finding(n, "FIXED", actor="user:slobodan")
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)
            zadaci.finish(z)
        z.refresh_from_db()
        assert z.status == E.TaskStatus.DONE.value


class TestKomanda:
    def test_upis_i_spisak(self, z):
        out = io.StringIO()
        call_command("nalaz", "--zadatak", z.public_id, "--fajl",
                     "apps/content/lessons.py", "--linija", "131",
                     "--tvrdnja", "Ćuti o sečenju.", "--tezina", "BLOCKER", stdout=out)
        assert "BLOCKER" in out.getvalue()
        out = io.StringIO()
        call_command("nalaz", "--zadatak", z.public_id, "--spisak", stdout=out)
        ispis = out.getvalue()
        assert "lessons.py:131" in ispis and "Otvorenih BLOCKER nalaza: 1" in ispis

    def test_zatvaranje_po_prefiksu(self, z):
        n = _upisi(z)
        out = io.StringIO()
        call_command("nalaz", "--zadatak", z.public_id, "--zatvori", str(n.pk)[:8],
                     "--kako", "FIXED", stdout=out)
        assert "FIXED" in out.getvalue()
        n.refresh_from_db()
        assert n.status == "FIXED"

    def test_nepoznat_prefiks(self, z):
        _upisi(z)
        with pytest.raises(CommandError, match="Nijedan nalaz"):
            call_command("nalaz", "--zadatak", z.public_id, "--zatvori", "ffffffff",
                         stdout=io.StringIO())

    def test_dvosmislen_prefiks(self, z):
        """Kratak prefiks koji pogađa dva nalaza se odbija, ne pogađa se."""
        a, b = _upisi(z, "MAJOR", tvrdnja="prvi"), _upisi(z, "MAJOR", tvrdnja="drugi")
        zajednicki = ""
        for i in range(1, 33):
            if str(a.pk)[:i] == str(b.pk)[:i]:
                zajednicki = str(a.pk)[:i]
            else:
                break
        if not zajednicki:  # UUID-i se razilaze na prvom znaku — nema šta da se testira
            pytest.skip("identifikatori se razilaze odmah")
        with pytest.raises(CommandError, match="daj više znakova"):
            call_command("nalaz", "--zadatak", z.public_id, "--zatvori", zajednicki,
                         stdout=io.StringIO())

    def test_bez_fajla_i_tvrdnje(self, z):
        with pytest.raises(CommandError, match="Treba"):
            call_command("nalaz", "--zadatak", z.public_id, stdout=io.StringIO())

    def test_actor_mora_biti_covek(self, z):
        """Komanda koja daje `BLOCKER` ne sme da se pokrene u ime agenta."""
        with pytest.raises(CommandError, match="mora da počne sa `user:`"):
            call_command("nalaz", "--zadatak", z.public_id, "--fajl", "apps/content/x.py",
                         "--tvrdnja", "x", "--actor", "agent:P-00027",
                         stdout=io.StringIO())

    def test_prazan_spisak(self, z):
        out = io.StringIO()
        call_command("nalaz", "--zadatak", z.public_id, "--spisak", stdout=out)
        assert "nema nijedan nalaz" in out.getvalue()

    def test_nepostojeci_zadatak(self, db):
        with pytest.raises(CommandError, match="ne postoji"):
            call_command("nalaz", "--zadatak", "TSK-01M3C15CJ999KE2FX8PG6KHMZE",
                         "--spisak", stdout=io.StringIO())


def test_nalaz_bez_tvrdnje_nije_nalaz(z):
    with bind(actor_id="user:slobodan"), \
         pytest.raises(zadaci.TaskError, match="nije nalaz"):
        zadaci.add_finding(z, reviewer=None, file="apps/content/x.py", claim="  ",
                           severity="MAJOR", source=zadaci.IZVOR_COVEK)


def test_recenzent_koji_je_autor_se_odbija(z, mila):
    with bind(actor_id="user:slobodan"), \
         pytest.raises(zadaci.TaskError, match="sopstveni rad"):
        zadaci.add_finding(z, reviewer=mila, file="apps/content/x.py", claim="x",
                           severity="MAJOR", source=zadaci.IZVOR_COVEK)


def test_stranac_kao_recenzent_sme(z, db):
    drugi = Persona.objects.create(public_id="P-09400", display_name="Recenzent",
                                   persona_type=E.PersonaType.ASSISTANT,
                                   status=E.PersonaStatus.ACTIVE)
    with bind(actor_id="user:slobodan"):
        n = zadaci.add_finding(z, reviewer=drugi, file="apps/content/x.py",
                               claim="x", severity="MINOR", source="open-code-review")
    assert isinstance(n, ReviewFinding)


class TestIspravka:
    """ADR-0046 — greška u kucanju ne sme da tera na lažno zatvaranje nalaza."""

    def test_covek_ispravlja_tvrdnju(self, z):
        n = _upisi(z, tvrdnja="Ceti o secenju.")
        with bind(actor_id="user:slobodan"):
            zadaci.amend_finding(n, "Ćuti o sečenju.", actor="user:slobodan")
        n.refresh_from_db()
        assert n.claim == "Ćuti o sečenju."

    def test_tezina_i_status_ostaju(self, z):
        n = _upisi(z)
        with bind(actor_id="user:slobodan"):
            zadaci.amend_finding(n, "drugi tekst", actor="user:slobodan")
        n.refresh_from_db()
        assert n.severity == "BLOCKER" and n.status == "OPEN"

    def test_zatvoren_nalaz_se_ne_prepravlja(self, z):
        """Presuđen nalaz je deo presude; ispravka bi bila prepravljanje istorije."""
        n = _upisi(z)
        with bind(actor_id="user:slobodan"):
            zadaci.close_finding(n, "FIXED", actor="user:slobodan")
            with pytest.raises(zadaci.TaskError, match="ne prepravlja"):
                zadaci.amend_finding(n, "novo", actor="user:slobodan")

    def test_izvrsilac_ne_dira_svoj(self, z, mila):
        n = _upisi(z)
        with bind(actor_id=f"agent:{mila.public_id}"), \
             pytest.raises(zadaci.TaskError, match="sopstveni rad"):
            zadaci.amend_finding(n, "nema problema", actor=f"agent:{mila.public_id}")

    def test_prazna_tvrdnja_se_odbija(self, z):
        n = _upisi(z)
        with bind(actor_id="user:slobodan"), \
             pytest.raises(zadaci.TaskError, match="nije nalaz"):
            zadaci.amend_finding(n, "   ", actor="user:slobodan")

    def test_stara_tvrdnja_ostaje_u_auditu(self, z):
        from apps.observability.models import AuditEvent

        n = _upisi(z, tvrdnja="prva verzija")
        with bind(actor_id="user:slobodan"):
            zadaci.amend_finding(n, "druga verzija", actor="user:slobodan")
        red = AuditEvent.objects.filter(event_key="task.finding.amended").first()
        assert red.payload["details"]["pre"] == "prva verzija"
        assert red.payload["details"]["posle"] == "druga verzija"

    def test_komanda_ispravlja(self, z):
        n = _upisi(z, tvrdnja="Ceti o secenju.")
        out = io.StringIO()
        call_command("nalaz", "--zadatak", z.public_id, "--izmeni", str(n.pk)[:8],
                     "--tvrdnja", "Ćuti o sečenju.", stdout=out)
        ispis = out.getvalue()
        assert "ispravljena" in ispis and "Ćuti o sečenju." in ispis
        n.refresh_from_db()
        assert n.claim == "Ćuti o sečenju."

    def test_komanda_trazi_tvrdnju(self, z):
        n = _upisi(z)
        with pytest.raises(CommandError, match="ide `--tvrdnja`"):
            call_command("nalaz", "--zadatak", z.public_id, "--izmeni",
                         str(n.pk)[:8], stdout=io.StringIO())
