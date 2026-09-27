"""ADR-0038 — zakrpa kao kapija.

Ovde se brane četiri zamke koje naivno čitanje zakrpe propušta, i one su razlog
zašto ovaj modul uopšte postoji:

  1. preimenovanje nosi DVE putanje — ko proverava samo novu, propušta izmenu u
     zaštićenoj zoni izvedenu preimenovanjem;
  2. `..` i apsolutna putanja izlaze iz radnog direktorijuma;
  3. mod `120000` pravi simbolički link i time gasi sve provere putanja;
  4. putanja u navodnicima se mora dekodirati pre provere.

Peta stvar koja se brani: odbijena zakrpa se pamti, jer je podatak o agentu.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command

from api.context import bind
from apps.orchestration import zadaci, zakrpa
from apps.orchestration.models import TaskPatch
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]


def _diff(putanja="apps/content/steps.py", telo=None):
    return telo or (
        f"diff --git a/{putanja} b/{putanja}\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/{putanja}\n"
        f"+++ b/{putanja}\n"
        "@@ -1,3 +1,3 @@\n"
        " prvi\n"
        "-drugi\n"
        "+drugi red\n"
        " treci\n"
    )


@pytest.fixture
def z(mila):
    with bind(actor_id="user:slobodan"):
        policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                            actor="user:slobodan", reason="proba", scope="apps/content")
        zad = zadaci.create(
            title="Navodnici", why="Marketing javlja da nacrt gubi navodnike.",
            allowed_paths=["apps/content"], assignee=mila)
    return zad


class TestCitanje:
    def test_obicna_izmena(self):
        izmene = zakrpa.paths_in(_diff())
        assert [(i.path, i.kind) for i in izmene] == [
            ("apps/content/steps.py", "izmena")]

    def test_nov_fajl(self):
        d = ("diff --git a/apps/content/novo.py b/apps/content/novo.py\n"
             "new file mode 100644\n"
             "--- /dev/null\n"
             "+++ b/apps/content/novo.py\n"
             "@@ -0,0 +1 @@\n+prvi red\n")
        assert [(i.path, i.kind) for i in zakrpa.paths_in(d)] == [
            ("apps/content/novo.py", "nova")]

    def test_brisanje(self):
        d = ("diff --git a/apps/content/staro.py b/apps/content/staro.py\n"
             "deleted file mode 100644\n"
             "--- a/apps/content/staro.py\n"
             "+++ /dev/null\n"
             "@@ -1 +0,0 @@\n-prvi red\n")
        assert [(i.path, i.kind) for i in zakrpa.paths_in(d)] == [
            ("apps/content/staro.py", "brisanje")]

    def test_prazna_i_prevelika(self):
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in("   ")
        assert e.value.code == "EMPTY_PATCH"
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in("x" * (zakrpa.MAX_DIFF_BYTES + 1))
        assert e.value.code == "PATCH_TOO_BIG"

    def test_tekst_koji_nije_diff(self):
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in("evo sam popravio, veruj mi\n")
        assert e.value.code == "NO_PATHS"


class TestZamke:
    """Četiri zamke iz ADR-0038 §3."""

    def test_preimenovanje_daje_obe_putanje(self):
        d = ("diff --git a/apps/content/a.py b/apps/policy/b.py\n"
             "similarity index 100%\n"
             "rename from apps/content/a.py\n"
             "rename to apps/policy/b.py\n")
        putanje = {i.path for i in zakrpa.paths_in(d)}
        assert putanje == {"apps/content/a.py", "apps/policy/b.py"}

    def test_preimenovanje_u_zasticenu_zonu_pada(self, z):
        d = ("diff --git a/apps/content/a.py b/apps/policy/b.py\n"
             "similarity index 100%\n"
             "rename from apps/content/a.py\n"
             "rename to apps/policy/b.py\n")
        nalaz = zakrpa.check(z, d)
        assert not nalaz.ok
        assert any("zaštićena zona" in r for _, r in nalaz.odbijeno)

    @pytest.mark.parametrize("putanja", [
        "../../etc/passwd", "apps/content/../../../etc/passwd",
    ])
    def test_izlazak_iz_direktorijuma(self, putanja):
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(_diff(putanja))
        assert e.value.code == "PATH_ESCAPE"

    @pytest.mark.parametrize("putanja", ["/etc/passwd", "C:\\Windows\\system32"])
    def test_apsolutna_putanja(self, putanja):
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(_diff(putanja))
        assert e.value.code == "ABSOLUTE_PATH"

    @pytest.mark.parametrize("red", [
        "new file mode 120000", "old mode 120000", "new mode 120000",
        "deleted file mode 120000",
    ])
    def test_simbolicki_link(self, red):
        d = (f"diff --git a/apps/content/x b/apps/content/x\n{red}\n"
             "--- /dev/null\n+++ b/apps/content/x\n@@ -0,0 +1 @@\n+/etc/passwd\n")
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(d)
        assert e.value.code == "SYMLINK"

    def test_navodnici_se_dekoduju(self):
        d = ('diff --git "a/apps/content/ime\\tsa tabom.py" '
             '"b/apps/content/ime\\tsa tabom.py"\n'
             '--- "a/apps/content/ime\\tsa tabom.py"\n'
             '+++ "b/apps/content/ime\\tsa tabom.py"\n'
             "@@ -1 +1 @@\n-a\n+b\n")
        assert zakrpa.paths_in(d)[0].path == "apps/content/ime\tsa tabom.py"

    def test_navodnici_kriju_izlazak(self):
        d = ('diff --git "a/apps/content/../../x" "b/apps/content/../../x"\n'
             '--- "a/apps/content/../../x"\n+++ "b/apps/content/../../x"\n')
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(d)
        assert e.value.code == "PATH_ESCAPE"

    def test_pokvareni_navodnici(self):
        d = ('diff --git "a/apps/content/x\\q" "b/apps/content/x\\q"\n')
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(d)
        assert e.value.code == "BAD_PATH"

    @pytest.mark.parametrize("red", [
        "GIT binary patch", "Binary files a/x.png and b/x.png differ"])
    def test_binarna_zakrpa(self, red):
        d = f"diff --git a/apps/content/x.png b/apps/content/x.png\n{red}\n"
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(d)
        assert e.value.code == "BINARY_PATCH"


class TestAritmetikaHunkova:
    """ADR-0049 — `@@` zaglavlje se proverava prebrojavanjem, bez `git`-a.

    27.09. je Lazar vratio zakrpu sa oba `@@` zaglavlja pogrešna:

        red 3  : prijavljeno -6  +20 | izbrojano -6  +18
        red 22 : prijavljeno -14 +45 | izbrojano -17 +45

    Naš lanac ju je pustio kao `ACCEPTED`, poslušnik ju je odbio kao
    `corrupt patch at line 22` i — do ovog ADR-a — upisao lažnu palu kapiju
    `pytest`. Aritmetika koju umemo da uradimo sami ne čeka `git apply`.
    """

    def _d(self, zaglavlje: str, telo: str) -> str:
        return ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
                "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n"
                f"{zaglavlje}\n{telo}")

    def test_tacno_zaglavlje_prolazi(self):
        d = self._d("@@ -2,3 +2,4 @@", " prvi\n-drugi\n+drugi red\n+novi\n treci\n")
        assert [i.path for i in zakrpa.paths_in(d)] == ["apps/content/x.py"]

    def test_izostavljen_broj_znaci_jedan(self):
        """`@@ -1 +1 @@` je isto što i `-1,1 +1,1` — ne sme da padne."""
        assert zakrpa.paths_in(self._d("@@ -1 +1 @@", "-a\n+b\n"))

    @pytest.mark.parametrize("zaglavlje,telo,greska", [
        # premalo dodatih redova nego što zaglavlje tvrdi
        ("@@ -1,1 +1,3 @@", "-a\n+b\n", "-1 +1"),
        # premalo skinutih
        ("@@ -1,3 +1,1 @@", "-a\n+b\n", "-1 +1"),
        # kontekstni red se broji na OBE strane — ko ga zaboravi, promaši oba zbira
        ("@@ -1,2 +1,3 @@", " prvi\n-a\n+b\n", "-2 +2"),
    ])
    def test_pogresno_zaglavlje_pada(self, zaglavlje, telo, greska):
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(self._d(zaglavlje, telo))
        assert e.value.code == "BAD_HUNK"
        assert greska in str(e.value), str(e.value)

    def test_poruka_kaze_koji_red_i_koliko(self):
        """Pisac mora da zna gde da gleda, inače popravlja naslepo (ADR-0033)."""
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(self._d("@@ -1,1 +1,9 @@", "-a\n+b\n"))
        poruka = str(e.value)
        assert "redu 4" in poruka, poruka          # `@@` je četvrti red ove zakrpe
        assert "-1 +9" in poruka and "-1 +1" in poruka
        assert "prebroj redove" in poruka

    def test_drugi_hunk_pada_i_kad_je_prvi_dobar(self):
        """Poslušnik je 27.09. prijavio red 22 — dakle drugi hunk, ne prvi."""
        d = (self._d("@@ -1 +1 @@", "-a\n+b\n")
             + "@@ -10,2 +10,5 @@\n konteks\n+dodato\n")
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(d)
        assert "-2 +5" in str(e.value) and "-1 +2" in str(e.value)

    def test_hunk_drugog_fajla_se_ne_slepljuje(self):
        """Bez granice po fajlu bi se redovi drugog fajla brojali u prvi hunk."""
        d = (self._d("@@ -1 +1 @@", "-a\n+b\n")
             + "diff --git a/apps/content/y.py b/apps/content/y.py\n"
               "--- a/apps/content/y.py\n+++ b/apps/content/y.py\n"
               "@@ -1 +1 @@\n-c\n+d\n")
        assert len(zakrpa.paths_in(d)) == 2

    def test_granica_i_bez_diff_git_reda(self):
        """ADR-0048 — zakrpa bez `diff --git`; par `---`/`+++` je granica fajla."""
        d = ("--- a/apps/content/x.py\n+++ b/apps/content/x.py\n@@ -1 +1 @@\n-a\n+b\n"
             "--- a/apps/content/y.py\n+++ b/apps/content/y.py\n@@ -1 +1 @@\n-c\n+d\n")
        assert len(zakrpa.paths_in(d)) == 2

    def test_bez_novog_reda_na_kraju_se_ne_broji(self):
        r"""`\ No newline at end of file` nije ni dodat ni skinut red."""
        d = self._d("@@ -1 +1 @@", "-a\n+b\n\\ No newline at end of file\n")
        assert zakrpa.paths_in(d)

    def test_prazan_red_je_kontekst(self):
        """Uređivači seku prateći razmak, pa prazan red u hunku znači ` `."""
        d = self._d("@@ -1,2 +1,2 @@", "-a\n+b\n\n")
        assert zakrpa.paths_in(d)

    def test_proza_u_hunku_pada(self):
        d = self._d("@@ -1 +1 @@", "-a\n+b\nevo, ovo bi trebalo da radi\n")
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.paths_in(d)
        assert e.value.code == "BAD_HUNK"
        assert "ne počinje razmakom" in str(e.value)

    def test_preimenovanje_bez_hunka_prolazi(self):
        """Valjana zakrpa ume da nema ni jedan `@@` — prvo mesto provere je grešilo."""
        d = ("diff --git a/apps/content/a.py b/apps/content/b.py\n"
             "similarity index 100%\n"
             "rename from apps/content/a.py\n"
             "rename to apps/content/b.py\n")
        assert len(zakrpa.paths_in(d)) == 2

    def test_pokvarena_zakrpa_se_pamti_kao_odbijena(self, z, mila):
        """Agentov promašaj ostaje agentov — ali sa porukom koja se može pročitati."""
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, self._d("@@ -1,1 +1,4 @@", "-a\n+b\n"),
                                persona=mila)
        assert red.status == E.PatchStatus.REJECTED
        assert "BAD_HUNK" in red.reason


class TestNeprimenjenaZakrpa:
    """ADR-0049 — zakrpa koja je prošla proveru, a nije se primenila.

    Do ovog ADR-a je poslušnik na svaku grešku van kapija upisivao `pytest: False`,
    jer je to bio jedini način da posao izađe iz reda. Time je `ucinak` brojao pale
    testove koji nikad nisu pokrenuti.
    """

    def test_status_i_razlog(self, z, mila):
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, _diff(), persona=mila)
            red = zakrpa.odbij_posle_provere(z, red, "apply --check: corrupt patch")
        assert red.status == E.PatchStatus.REJECTED
        assert "nije se primenila" in red.reason and "corrupt patch" in red.reason

    def test_nijedna_kapija_se_ne_upisuje(self, z, mila):
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, _diff(), persona=mila)
            zakrpa.odbij_posle_provere(z, red, "nema mesta na disku")
        assert not red.gates.exists()
        # `gate_report` nabraja tražene kapije; nijedna ne sme da ima ishod
        assert set(zadaci.gate_report(z).values()) == {None}

    def test_izlazi_iz_reda_poslusnika(self, z, mila):
        """Red gleda `ACCEPTED` bez kapija — odbijena zakrpa iz njega izlazi."""
        from apps.orchestration.models import CodeTask
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, _diff(), persona=mila)
        nemereno = TaskPatch.objects.filter(status=E.PatchStatus.ACCEPTED.value,
                                            gates__isnull=True)
        assert CodeTask.objects.filter(patches__in=nemereno, pk=z.pk).exists()
        with bind(actor_id="user:slobodan"):
            zakrpa.odbij_posle_provere(z, red, "corrupt patch")
        nemereno = TaskPatch.objects.filter(status=E.PatchStatus.ACCEPTED.value,
                                            gates__isnull=True)
        assert not CodeTask.objects.filter(patches__in=nemereno, pk=z.pk).exists()

    def test_izmerena_zakrpa_se_ne_prepravlja(self, z, mila):
        """Kapije su zapis; ne brišu se time što je nešto posle njih puklo."""
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, _diff(), persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=red)
            with pytest.raises(zadaci.TaskError) as e:
                zakrpa.odbij_posle_provere(z, red, "push je pao")
        assert e.value.code == "ALREADY_MEASURED"
        red.refresh_from_db()
        assert red.status == E.PatchStatus.ACCEPTED

    def test_tudja_zakrpa_se_odbija(self, z, mila):
        with bind(actor_id="user:slobodan"):
            drugi = zadaci.create(title="Drugi", why="Provera vlasništva.",
                                  allowed_paths=["apps/content"], assignee=mila)
            red = zakrpa.submit(z, _diff(), persona=mila)
            with pytest.raises(zadaci.TaskError) as e:
                zakrpa.odbij_posle_provere(drugi, red, "greška")
        assert e.value.code == "WRONG_TASK"

    def test_upisuje_se_u_zapis(self, z, mila):
        from apps.observability.models import AuditEvent
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, _diff(), persona=mila)
            zakrpa.odbij_posle_provere(z, red, "corrupt patch at line 22")
        assert AuditEvent.objects.filter(event_key="task.patch.unapplied").exists()


class TestProvera:
    def test_zakrpa_u_svom_delu_prolazi(self, z):
        assert zakrpa.check(z, _diff()).ok

    def test_van_dozvoljenih_putanja(self, z):
        nalaz = zakrpa.check(z, _diff("apps/memory/writer.py"))
        assert not nalaz.ok
        assert "van dozvoljenih" in nalaz.odbijeno[0][1]

    def test_zasticena_zona(self, z):
        nalaz = zakrpa.check(z, _diff("apps/policy/service.py"))
        assert "zaštićena zona" in nalaz.odbijeno[0][1]

    def test_jedna_losa_putanja_obara_celu_zakrpu(self, z):
        d = _diff() + _diff("apps/policy/service.py")
        nalaz = zakrpa.check(z, d)
        assert not nalaz.ok
        assert len(nalaz.izmene) == 2 and len(nalaz.odbijeno) == 1

    def test_poverenje_skinuto_obara_zakrpu(self, z, mila):
        with bind(actor_id="user:slobodan"):
            policy.change_trust(mila, "code.write", E.TrustLevel.L0,
                                actor="user:slobodan", reason="pauza",
                                scope="apps/content")
        assert not zakrpa.check(z, _diff()).ok

    def test_greska_u_citanju_ne_ruši_proveru(self, z):
        nalaz = zakrpa.check(z, "ovo nije diff")
        assert not nalaz.ok and nalaz.greske and not nalaz.izmene


class TestPredaja:
    def test_prihvacena_se_pamti(self, z, mila):
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, _diff(), persona=mila, base_sha="9f65d41")
        assert red.status == E.PatchStatus.ACCEPTED
        assert red.paths == ["apps/content/steps.py"] and red.base_sha == "9f65d41"

    def test_odbijena_se_takodje_pamti(self, z, mila):
        """Odbijena zakrpa je podatak o agentu, ne smeće (ADR-0034 §6)."""
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, _diff("apps/policy/service.py"), persona=mila)
        assert red.status == E.PatchStatus.REJECTED
        assert "zaštićena zona" in red.reason
        assert TaskPatch.objects.count() == 1

    def test_nečitljiva_zakrpa_se_pamti_sa_razlogom(self, z, mila):
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, "veruj mi na reč", persona=mila)
        assert red.status == E.PatchStatus.REJECTED and "NO_PATHS" in red.reason


class TestKomanda:
    def _fajl(self, tmp_path, tekst):
        p = tmp_path / "izmena.diff"
        p.write_text(tekst, encoding="utf-8")
        return str(p)

    def test_proveri_ne_upisuje(self, z, tmp_path):
        out = io.StringIO()
        call_command("zakrpa", "--zadatak", z.public_id, "--iz",
                     self._fajl(tmp_path, _diff()), "--proveri", stdout=out)
        assert "Zakrpa prolazi" in out.getvalue()
        assert not TaskPatch.objects.exists()

    def test_predaj_upisuje(self, z, tmp_path):
        out = io.StringIO()
        call_command("zakrpa", "--zadatak", z.public_id, "--iz",
                     self._fajl(tmp_path, _diff()), "--predaj", stdout=out)
        assert "ACCEPTED" in out.getvalue() and TaskPatch.objects.count() == 1

    def test_zona_se_vidi_u_ispisu(self, z, tmp_path):
        out = io.StringIO()
        call_command("zakrpa", "--zadatak", z.public_id, "--iz",
                     self._fajl(tmp_path, _diff("apps/policy/service.py")),
                     "--proveri", stdout=out)
        assert "NE SME" in out.getvalue() and "ne primenjuje" in out.getvalue()

    def test_tacno_jedno_od_dva(self, z, tmp_path):
        with pytest.raises(CommandError, match="tačno jedno"):
            call_command("zakrpa", "--zadatak", z.public_id, "--iz",
                         self._fajl(tmp_path, _diff()), stdout=io.StringIO())
