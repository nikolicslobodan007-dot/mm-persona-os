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
    """ADR-0049 + ADR-0052 — `@@` zaglavlje se prebrojava iz tela hunka.

    27.09. je Lazar tri puta vratio zakrpu sa pogrešnim zaglavljem:

        prijavljeno -6 +20, pa -6 +19 | izbrojano -6 +18

    Pomerao se za jedan — to je pogađanje, ne brojanje. ADR-0049 je takvu zakrpu
    odbijao; ADR-0052 je ispravlja, jer za dato telo postoji tačno jedan ispravan
    par brojeva, pa se ništa ne nagađa. Ispravka nije tiha: ide u `reason`.
    """

    def _d(self, zaglavlje: str, telo: str) -> str:
        return ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
                "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n"
                f"{zaglavlje}\n{telo}")

    def test_tacno_zaglavlje_ostaje_netaknuto(self):
        d = self._d("@@ -2,3 +2,4 @@", " prvi\n-drugi\n+drugi red\n+novi\n treci\n")
        izlaz, ispravke = zakrpa.prebroj_hunkove(d)
        assert not ispravke and izlaz == d

    def test_izostavljen_broj_znaci_jedan(self):
        """`@@ -1 +1 @@` je isto što i `-1,1 +1,1` — ne sme da se dira."""
        izlaz, ispravke = zakrpa.prebroj_hunkove(self._d("@@ -1 +1 @@", "-a\n+b\n"))
        assert not ispravke and "@@ -1 +1 @@" in izlaz

    @pytest.mark.parametrize("zaglavlje,telo,ocekivano", [
        ("@@ -1,1 +1,3 @@", "-a\n+b\n", "@@ -1,1 +1,1 @@"),
        ("@@ -1,3 +1,1 @@", "-a\n+b\n", "@@ -1,1 +1,1 @@"),
        # kontekstni red se broji na OBE strane
        ("@@ -1,2 +1,3 @@", " prvi\n-a\n+b\n", "@@ -1,2 +1,2 @@"),
        # tačno slučaj sa proizvodnje: telo ima 18 dodatih, zaglavlje tvrdilo 20
        ("@@ -6,20 +22,45 @@", "-a\n" + "+r\n" * 18, "@@ -6,1 +22,18 @@"),
    ])
    def test_pogresno_zaglavlje_se_prebroji(self, zaglavlje, telo, ocekivano):
        izlaz, ispravke = zakrpa.prebroj_hunkove(self._d(zaglavlje, telo))
        assert ocekivano in izlaz, izlaz
        assert len(ispravke) == 1

    def test_pocetni_brojevi_reda_se_ne_diraju(self):
        """Oni nose nameru i nisu izvedivi iz tela — računati ih bilo bi nagađanje."""
        izlaz, _ = zakrpa.prebroj_hunkove(self._d("@@ -6,20 +22,45 @@", "-a\n+b\n"))
        assert "@@ -6,1 +22,1 @@" in izlaz

    def test_oznaka_odeljka_ostaje(self):
        """`git` iza drugog `@@` piše ime funkcije; to se prenosi netaknuto."""
        d = self._d("@@ -1,9 +1,9 @@ def prompt_section(self):", "-a\n+b\n")
        izlaz, _ = zakrpa.prebroj_hunkove(d)
        assert "@@ -1,1 +1,1 @@ def prompt_section(self):" in izlaz

    def test_ispravka_kaze_red_i_oba_broja(self):
        _, ispravke = zakrpa.prebroj_hunkove(self._d("@@ -1,1 +1,9 @@", "-a\n+b\n"))
        assert str(ispravke[0]) == "red 4: -1 +9 → -1 +1"

    def test_drugi_hunk_se_prebroji_i_kad_je_prvi_dobar(self):
        d = (self._d("@@ -1 +1 @@", "-a\n+b\n")
             + "@@ -10,2 +10,5 @@\n konteks\n+dodato\n")
        izlaz, ispravke = zakrpa.prebroj_hunkove(d)
        assert len(ispravke) == 1 and ispravke[0].red == 7
        assert "@@ -10,1 +10,2 @@" in izlaz and "@@ -1 +1 @@" in izlaz

    def test_hunk_drugog_fajla_se_ne_slepljuje(self):
        d = (self._d("@@ -1 +1 @@", "-a\n+b\n")
             + "diff --git a/apps/content/y.py b/apps/content/y.py\n"
               "--- a/apps/content/y.py\n+++ b/apps/content/y.py\n"
               "@@ -1 +1 @@\n-c\n+d\n")
        izlaz, ispravke = zakrpa.prebroj_hunkove(d)
        assert not ispravke and izlaz == d
        assert len(zakrpa.paths_in(d)) == 2

    def test_granica_i_bez_diff_git_reda(self):
        """ADR-0048 — zakrpa bez `diff --git`; par `---`/`+++` je granica fajla."""
        d = ("--- a/apps/content/x.py\n+++ b/apps/content/x.py\n@@ -1 +1 @@\n-a\n+b\n"
             "--- a/apps/content/y.py\n+++ b/apps/content/y.py\n@@ -1 +1 @@\n-c\n+d\n")
        _, ispravke = zakrpa.prebroj_hunkove(d)
        assert not ispravke and len(zakrpa.paths_in(d)) == 2

    def test_bez_novog_reda_na_kraju_se_ne_broji(self):
        r"""`\ No newline at end of file` nije ni dodat ni skinut red."""
        d = self._d("@@ -1 +1 @@", "-a\n+b\n\\ No newline at end of file\n")
        _, ispravke = zakrpa.prebroj_hunkove(d)
        assert not ispravke

    def test_prazan_red_je_kontekst(self):
        """Uređivači seku prateći razmak, pa prazan red u hunku znači ` `."""
        _, ispravke = zakrpa.prebroj_hunkove(self._d("@@ -1,2 +1,2 @@", "-a\n+b\n\n"))
        assert not ispravke

    def _nov(self, zaglavlje: str, telo: str) -> str:
        return ("diff --git a/apps/content/nov.py b/apps/content/nov.py\n"
                "new file mode 100644\n"
                "--- /dev/null\n+++ b/apps/content/nov.py\n"
                f"{zaglavlje}\n{telo}")

    def test_nov_fajl_zadrzava_nula_starih_redova(self):
        """ADR-0052 — 29.09. je naš ispravljač od `-0,0` napravio `-0,1`.

        Prazan red na kraju tela izbrojan je kao kontekst, a nov fajl kontekst
        nema. `git apply` takvu zakrpu odbije, i to bi u zapisu stajalo kao
        agentov neuspeh iako je kvar naš.
        """
        d = self._nov("@@ -0,0 +1,2 @@", "+a\n+b\n")
        izlaz, ispravke = zakrpa.prebroj_hunkove(d)
        assert not ispravke, "telo od dva `+` reda je tačno prijavljeno"
        assert "@@ -0,0 +1,2 @@" in izlaz
        assert "-0,1" not in izlaz

    def test_prazan_red_usred_novog_fajla_dobija_nazad_plus(self):
        """29.09., drugi krug: prva ispravka je prekidala telo na praznom redu.

        Prazan red je bio **usred** novog fajla — između dve funkcije — pa je
        hunk od 58 redova prijavljen kao 21 i `git apply` je pukao na sledećem
        fajlu. `git` prazan red u telu čita kao kontekst i sam odbija hunk
        novog fajla, pa broj nije dovoljan: redu se vraća njegov `+`.
        """
        telo = "+def a():\n+    return 1\n\n+def b():\n+    return 2\n"
        izlaz, ispravke = zakrpa.prebroj_hunkove(self._nov("@@ -0,0 +1,5 @@", telo))
        assert [i.posle for i in ispravke] == [(0, 5)]
        assert [i.prazni for i in ispravke] == [1]
        assert "@@ -0,0 +1,5 @@" in izlaz
        # Prazan red više nije prazan: nosi svoj `+`.
        assert "+    return 1\n+\n+def b():" in izlaz
        assert "prazn" in str(ispravke[0])

    def test_prazan_red_u_obicnom_hunku_ostaje_kontekst(self):
        """Granica ide samo oko novog fajla; svuda drugde pravilo je staro."""
        izlaz, ispravke = zakrpa.prebroj_hunkove(
            self._d("@@ -1,2 +1,2 @@", "-a\n+b\n\n"))
        assert not ispravke
        assert "+\n" not in izlaz

    def test_nov_fajl_sa_pogresnim_brojem_se_ispravi_na_nula(self):
        d = self._nov("@@ -0,0 +1,9 @@", "+a\n+b\n+c\n")
        izlaz, ispravke = zakrpa.prebroj_hunkove(d)
        assert [i.posle for i in ispravke] == [(0, 3)]
        assert "@@ -0,0 +1,3 @@" in izlaz

    def test_nov_fajl_sa_kontekstom_pada_umesto_da_se_ispravi(self):
        """Nemoguć oblik se ne upisuje tiho — staje se i kaže se zašto."""
        d = self._nov("@@ -0,0 +1,2 @@", "+a\n stari red\n+b\n")
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.prebroj_hunkove(d)
        assert e.value.code == "BAD_HUNK"
        assert "nov fajl" in str(e.value).lower()

    def test_proza_u_hunku_i_dalje_pada(self):
        """Red koji se ne može prebrojati ne može ni da se ispravi."""
        d = self._d("@@ -1 +1 @@", "-a\n+b\nevo, ovo bi trebalo da radi\n")
        with pytest.raises(zakrpa.PatchError) as e:
            zakrpa.prebroj_hunkove(d)
        assert e.value.code == "BAD_HUNK"
        assert "ne počinje razmakom" in str(e.value)

    def test_preimenovanje_bez_hunka_prolazi(self):
        """Valjana zakrpa ume da nema ni jedan `@@`."""
        d = ("diff --git a/apps/content/a.py b/apps/content/b.py\n"
             "similarity index 100%\n"
             "rename from apps/content/a.py\n"
             "rename to apps/content/b.py\n")
        izlaz, ispravke = zakrpa.prebroj_hunkove(d)
        assert not ispravke and izlaz == d
        assert len(zakrpa.paths_in(d)) == 2


class TestIspravkaSeVidi:
    """ADR-0052 — tiha ispravka je opasna; ova se upisuje i stoji pred recenzentom.

    Ako je pisac hteo duži hunk pa ga je odsekao, zaglavlje je jedini trag te
    namere. Prebrojavanje bi tu nameru izbrisalo — osim ako se ne zapiše.
    """

    POKVARENA = ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
                 "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n"
                 "@@ -1,1 +1,9 @@\n-a\n+b\n")

    def test_zakrpa_je_prihvacena(self, z, mila):
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, self.POKVARENA, persona=mila)
        assert red.status == E.PatchStatus.ACCEPTED

    def test_cuva_se_ispravljena_zakrpa(self, z, mila):
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, self.POKVARENA, persona=mila)
        assert "@@ -1,1 +1,1 @@" in red.diff and "+1,9" not in red.diff

    def test_razlog_nosi_ispravku(self, z, mila):
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, self.POKVARENA, persona=mila)
        assert "ADR-0052" in red.reason
        assert "-1 +9 → -1 +1" in red.reason
        assert "odsečen" in red.reason

    def test_ispravna_zakrpa_nema_sta_da_prijavi(self, z, mila):
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, _diff(), persona=mila)
        assert red.reason == "" and red.status == E.PatchStatus.ACCEPTED

    def test_ispravka_ide_u_zapis(self, z, mila):
        from apps.observability.models import AuditEvent
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, self.POKVARENA, persona=mila)
        red = AuditEvent.objects.filter(event_key="task.patch.submitted").last()
        assert red.payload["details"]["ispravke"] == ["red 4: -1 +9 → -1 +1"]

    def test_zona_se_ne_prasta_zbog_ispravke(self, z, mila):
        """Prebrojavanje ne sme da spere proveru putanja."""
        losa = self.POKVARENA.replace("apps/content/x.py", "apps/policy/service.py")
        with bind(actor_id="user:slobodan"):
            red = zakrpa.submit(z, losa, persona=mila)
        assert red.status == E.PatchStatus.REJECTED
        assert "zaštićena zona" in red.reason


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


class TestRepHunka:
    """ADR-0065 — hunk bez završnog konteksta `git apply` odbija.

    01.10.2026. su tri zakrpe primljene kao `ACCEPTED` i sve tri odbijene kod
    poslušnika sa „patch does not apply". Bile su ispravne po svemu što smo
    proveravali; falio im je jedan red konteksta na kraju hunka. Provera je
    izmerena nad pravim `git`-om: 0 redova repa → odbija, 1 red → primenjuje se.
    """

    def _fajl(self, tmp_path, redova=20):
        (tmp_path / "apps").mkdir(parents=True, exist_ok=True)
        put = tmp_path / "apps" / "x.py"
        put.write_text("\n".join(f"red {i}" for i in range(1, redova + 1)) + "\n",
                       encoding="utf-8")
        return put

    def _diff(self, *, rep: int, pocetak: int = 5) -> str:
        ctx = [f"red {pocetak}", f"red {pocetak + 1}"]
        rem = [f"red {pocetak + 2}"]
        post = [f"red {pocetak + 3 + i}" for i in range(rep)]
        telo = ([" " + x for x in ctx] + ["-" + x for x in rem]
                + ["+novi red"] + [" " + x for x in post])
        st, nov = len(ctx) + len(rem) + rep, len(ctx) + 1 + rep
        return "\n".join(["--- a/apps/x.py", "+++ b/apps/x.py",
                          f"@@ -{pocetak},{st} +{pocetak},{nov} @@"] + telo) + "\n"

    def test_bez_repa_se_prijavljuje(self, tmp_path):
        self._fajl(tmp_path)
        greske = zakrpa.proveri_rep(self._diff(rep=0), tmp_path)
        assert len(greske) == 1
        assert "završava izmenjenim redom" in greske[0]
        assert "apps/x.py" in greske[0]

    def test_jedan_red_repa_je_dovoljan(self, tmp_path):
        self._fajl(tmp_path)
        assert zakrpa.proveri_rep(self._diff(rep=1), tmp_path) == []

    def test_hunk_do_kraja_fajla_ne_traži_rep(self, tmp_path):
        """Na kraju fajla repa nema odakle, pa ga ni `git` ne traži."""
        self._fajl(tmp_path, redova=8)          # hunk pokriva 5,6,7 → 7 == kraj? ne
        d = self._diff(rep=0, pocetak=6)        # 6,7,8 → kraj fajla
        assert zakrpa.proveri_rep(d, tmp_path) == []

    def test_fajl_koji_se_ne_moze_procitati_se_preskace(self, tmp_path):
        """Provera ne sme da obara ispravan rad kad sama ne vidi fajl."""
        assert zakrpa.proveri_rep(self._diff(rep=0), tmp_path) == []

    def test_vise_hunkova_prijavljuje_samo_onaj_bez_repa(self, tmp_path):
        self._fajl(tmp_path, redova=30)
        d = self._diff(rep=1, pocetak=5).rstrip("\n") + "\n" + "\n".join([
            "@@ -20,3 +20,3 @@", " red 20", "-red 21", "+drugi novi"]) + "\n"
        greske = zakrpa.proveri_rep(d, tmp_path)
        assert len(greske) == 1 and "red 7" not in greske[0]


class TestDopunaRepa:
    """ADR-0066 — izostavljeni rep hunka se dopunjuje iz fajla.

    01.10.2026., pet uzastopnih pokušaja: model napiše `@@ -186,10`, a u telu
    ostavi osam starih redova i završi izmenom. Sam je izbrojao da tamo idu još
    dva reda — samo ih nije otkucao. Koliko fali kaže njegovo zaglavlje, koji su
    to redovi kaže fajl. Dokazano nad pravim `git`-om: sirova zakrpa se odbija,
    dopunjena prolazi.
    """

    def _fajl(self, tmp_path, redova=20):
        (tmp_path / "apps").mkdir(parents=True, exist_ok=True)
        (tmp_path / "apps" / "x.py").write_text(
            "\n".join(f"red {i}" for i in range(1, redova + 1)) + "\n", encoding="utf-8")

    def _diff(self, *, trazeno: int, pocetak: int = 5) -> str:
        telo = [" red 5", " red 6", "-red 7", "+novi red"]
        return "\n".join(["--- a/apps/x.py", "+++ b/apps/x.py",
                          f"@@ -{pocetak},{trazeno} +{pocetak},3 @@"] + telo) + "\n"

    def test_dopunjuje_manjak_iz_fajla(self, tmp_path):
        self._fajl(tmp_path)
        nov, opisi = zakrpa.dopuni_rep(self._diff(trazeno=5), tmp_path)
        assert nov.splitlines()[-2:] == [" red 8", " red 9"]
        assert len(opisi) == 1 and "dopisano 2 red" in opisi[0]

    def test_posle_dopune_rep_vise_ne_fali(self, tmp_path):
        self._fajl(tmp_path)
        nov, _ = zakrpa.dopuni_rep(self._diff(trazeno=5), tmp_path)
        assert zakrpa.proveri_rep(nov, tmp_path) == []

    def test_bez_manjka_se_ne_dira(self, tmp_path):
        self._fajl(tmp_path)
        d = self._diff(trazeno=3)
        nov, opisi = zakrpa.dopuni_rep(d, tmp_path)
        assert nov == d and opisi == []

    def test_prevelik_manjak_se_ne_dopunjuje(self, tmp_path):
        """Manjak preko granice nije zaboravljen rep nego nešto drugo."""
        self._fajl(tmp_path)
        d = self._diff(trazeno=3 + zakrpa.NAJVISE_DOPUNE + 1)
        nov, opisi = zakrpa.dopuni_rep(d, tmp_path)
        assert nov == d and opisi == []

    def test_fajl_koji_se_ne_vidi_se_ne_dopunjuje(self, tmp_path):
        nov, opisi = zakrpa.dopuni_rep(self._diff(trazeno=5), tmp_path)
        assert opisi == []

    def test_dopuna_ne_ide_preko_kraja_fajla(self, tmp_path):
        """Zaglavlje koje traži više redova nego što fajl ima se ne izmišlja."""
        self._fajl(tmp_path, redova=7)
        nov, opisi = zakrpa.dopuni_rep(self._diff(trazeno=5), tmp_path)
        assert opisi == []

    def test_dopuna_se_vidi_u_razlogu(self, z, mila, db):
        """Naša ruka u tuđem radu se ne krije — ide u `reason` (ADR-0053)."""
        from pathlib import Path

        from django.conf import settings

        from apps.orchestration.models import TaskPatch
        fajl = Path(settings.BASE_DIR) / "apps/content/steps.py"
        redovi = fajl.read_text(encoding="utf-8").splitlines()
        telo = [" " + redovi[4], " " + redovi[5], "-" + redovi[6], "+# izmena"]
        d = "\n".join(["--- a/apps/content/steps.py", "+++ b/apps/content/steps.py",
                        "@@ -5,5 @@".replace("@@ -5,5 @@", "@@ -5,5 +5,3 @@")] + telo) + "\n"
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, d, persona=mila)
        red = TaskPatch.objects.order_by("-created_at").first()
        assert "ADR-0066" in red.reason, red.reason


class TestUsidri:
    """ADR-0067 — zaglavlje se pomera na mesto gde telo zaista stoji.

    01.10.2026.: model je deklarisao `@@ -186,9`, a telo je stajalo na redu 201.
    `git` to ne primećuje — traži telo po sadržaju i prijavi `offset 15 lines`.
    Ali `dopuni_rep` (ADR-0066) čita fajl po broju iz zaglavlja, pa je na
    ispravno telo dopisao red sa pogrešnog mesta i napravio zakrpu koja se ne
    primenjuje nigde. Zato se sidri prvo, i to po sadržaju kao i `git`.
    """

    def _fajl(self, tmp_path, puta=1):
        (tmp_path / "apps").mkdir(parents=True, exist_ok=True)
        blok = [f"red {i}" for i in range(1, 21)]
        (tmp_path / "apps" / "x.py").write_text(
            "\n".join(blok * puta) + "\n", encoding="utf-8")

    def _diff(self, *, pocetak: int, trazeno: int = 3) -> str:
        telo = [" red 10", " red 11", "-red 12", "+novi red"]
        return "\n".join(["--- a/apps/x.py", "+++ b/apps/x.py",
                          f"@@ -{pocetak},{trazeno} +{pocetak},3 @@"] + telo) + "\n"

    def test_pogresan_pocetak_se_pomera_na_pravo_mesto(self, tmp_path):
        self._fajl(tmp_path)
        nov, opisi = zakrpa.usidri(self._diff(pocetak=3), tmp_path)
        assert nov.splitlines()[2] == "@@ -10,3 +10,3 @@"
        assert len(opisi) == 1 and "+7" in opisi[0] and "ADR-0067" in opisi[0]

    def test_tacan_pocetak_se_ne_dira(self, tmp_path):
        self._fajl(tmp_path)
        d = self._diff(pocetak=10)
        nov, opisi = zakrpa.usidri(d, tmp_path)
        assert nov == d and opisi == []

    def test_telo_na_dva_mesta_se_ne_dira(self, tmp_path):
        """Dva mesta znače da bismo birali — a biranje je pogađanje."""
        self._fajl(tmp_path, puta=2)
        d = self._diff(pocetak=3)
        nov, opisi = zakrpa.usidri(d, tmp_path)
        assert nov == d and opisi == []

    def test_telo_koje_se_ne_nalazi_se_ne_dira(self, tmp_path):
        self._fajl(tmp_path)
        d = self._diff(pocetak=3).replace("red 11", "red kojeg nema")
        nov, opisi = zakrpa.usidri(d, tmp_path)
        assert nov == d and opisi == []

    def test_fajl_koji_se_ne_vidi_se_ne_dira(self, tmp_path):
        d = self._diff(pocetak=3)
        nov, opisi = zakrpa.usidri(d, tmp_path)
        assert nov == d and opisi == []

    def test_prekratko_telo_se_ne_sidri(self, tmp_path):
        self._fajl(tmp_path)
        d = "\n".join(["--- a/apps/x.py", "+++ b/apps/x.py", "@@ -3,1 +3,1 @@",
                       "-red 12", "+novi red"]) + "\n"
        nov, opisi = zakrpa.usidri(d, tmp_path)
        assert nov == d and opisi == []

    def test_bez_sidrenja_dopuna_uzima_red_sa_pogresnog_mesta(self, tmp_path):
        """Kvar od 01.10.2026., reprodukovan: dopuna veruje broju iz zaglavlja."""
        self._fajl(tmp_path)
        nov, _ = zakrpa.dopuni_rep(self._diff(pocetak=3, trazeno=4), tmp_path)
        assert nov.splitlines()[-1] == " red 6"

    def test_posle_sidrenja_dopuna_uzima_rep_sa_pravog_mesta(self, tmp_path):
        """Isti ulaz, ali usidren — rep dolazi odande gde telo stvarno stoji."""
        self._fajl(tmp_path)
        usidren, _ = zakrpa.usidri(self._diff(pocetak=3, trazeno=4), tmp_path)
        nov, opisi = zakrpa.dopuni_rep(usidren, tmp_path)
        assert nov.splitlines()[-1] == " red 13"
        assert len(opisi) == 1 and "redovi 13–13" in opisi[0]

    def test_sidrenje_se_vidi_u_razlogu(self, z, mila, db):
        """Naša ruka u tuđem radu se ne krije — ide u `reason` (ADR-0053)."""
        from pathlib import Path

        from django.conf import settings

        from apps.orchestration.models import TaskPatch
        redovi = (Path(settings.BASE_DIR) / "apps/content/steps.py").read_text(
            encoding="utf-8").splitlines()
        blok = redovi[19:22]
        assert sum(1 for k in range(len(redovi) - 2) if redovi[k:k + 3] == blok) == 1, (
            "fikstur traži da ova tri reda budu jedinstvena u fajlu")
        telo = [" " + blok[0], " " + blok[1], "-" + blok[2], "+# izmena"]
        d = "\n".join(["--- a/apps/content/steps.py", "+++ b/apps/content/steps.py",
                       "@@ -5,3 +5,3 @@"] + telo) + "\n"
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, d, persona=mila)
        red = TaskPatch.objects.order_by("-created_at").first()
        assert "ADR-0067" in red.reason, red.reason
        assert red.diff.splitlines()[2].startswith("@@ -20,"), red.diff
