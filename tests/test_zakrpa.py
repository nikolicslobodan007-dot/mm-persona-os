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
