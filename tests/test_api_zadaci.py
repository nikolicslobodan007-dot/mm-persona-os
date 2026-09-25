"""ADR-0039 — tri tačke za poslušnika i njegov nalog.

Glavna tvrdnja koja se ovde brani: **poslušnik je zatvoren svuda osim na te tri
tačke.** Token stoji na mašini koja vrti tuđi kod; da otvara išta drugo, ne bi
bio token nego problem.

Uz to: `work` nikad ne izdaje odbijenu zakrpu, `queued` vraća samo
identifikatore, a `gate` ne ume da zatvori zadatak.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.base import RUNNER_GROUP
from api.context import bind
from apps.orchestration import zadaci, zakrpa
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

#: Canon §8.5 — svaki POST nosi trag i pokretača. Test ide istim putem kao
#: poslušnik, pa nosi iste header-e.
_TRAG = {
    "HTTP_X_REQUEST_ID": "test-runner-0001",
    "HTTP_TRACEPARENT": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
}

DIFF = (
    "diff --git a/apps/content/steps.py b/apps/content/steps.py\n"
    "--- a/apps/content/steps.py\n"
    "+++ b/apps/content/steps.py\n"
    "@@ -1 +1 @@\n-a\n+b\n"
)
LOSA = (
    "diff --git a/apps/policy/service.py b/apps/policy/service.py\n"
    "--- a/apps/policy/service.py\n"
    "+++ b/apps/policy/service.py\n"
    "@@ -1 +1 @@\n-a\n+b\n"
)


@pytest.fixture
def poslusnik(db):
    u = User.objects.create_user(username="svc_runner")
    u.groups.set([Group.objects.get_or_create(name=RUNNER_GROUP)[0]])
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}",
                  HTTP_X_ACTOR_ID="service:runner", **_TRAG)
    return c


@pytest.fixture
def operater(db):
    u = User.objects.create_user(username="ana")
    u.groups.set([Group.objects.get_or_create(name=E.Role.OPERATOR.value)[0]])
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}",
                  HTTP_X_ACTOR_ID="user:ana", **_TRAG)
    return c


@pytest.fixture
def zad(mila):
    with bind(actor_id="user:slobodan"):
        policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                            actor="user:slobodan", reason="proba", scope="apps/content")
        z = zadaci.create(title="Proba", why="Provera tri tačke.",
                          allowed_paths=["apps/content"], assignee=mila)
    return z


def _predaj(z, diff, mila):
    with bind(actor_id="user:slobodan"):
        return zakrpa.submit(z, diff, persona=mila, base_sha="9f65d41")


class TestZatvorenoPodrazumevano:
    """Ovo je jedini razlog zašto `allow_runner` uopšte postoji."""

    def test_poslusnik_ne_vidi_audit(self, poslusnik, zad):
        assert poslusnik.get(reverse("audit")).status_code == 403

    def test_poslusnik_ne_vidi_persone(self, poslusnik, zad):
        assert poslusnik.get(reverse("personas")).status_code == 403

    def test_poslusnik_ne_vidi_odobrenja(self, poslusnik, zad):
        assert poslusnik.get(reverse("approvals")).status_code == 403

    def test_poslusnik_vidi_svoje_tri_tacke(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        assert poslusnik.get(reverse("tasks-queued")).status_code == 200
        assert poslusnik.get(
            reverse("task-work", args=[zad.public_id])).status_code == 200

    def test_dodata_uloga_ga_ne_otvara(self, poslusnik, db, zad):
        """I kad bi neko nalogu dodao ulogu, zatvorenost ostaje."""
        u = User.objects.get(username="svc_runner")
        u.groups.add(Group.objects.get_or_create(name=E.Role.SYSTEM_ADMIN.value)[0])
        assert poslusnik.get(reverse("audit")).status_code == 403

    def test_bez_prijave_nista(self, db, zad):
        assert APIClient().get(reverse("tasks-queued")).status_code in (401, 403)


class TestRed:
    def test_prazan_red_bez_zakrpe(self, poslusnik, zad):
        assert poslusnik.get(reverse("tasks-queued")).json()["data"]["tasks"] == []

    def test_zadatak_sa_prihvacenom_zakrpom_ulazi(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        assert poslusnik.get(reverse("tasks-queued")).json()["data"]["tasks"] == [
            zad.public_id]

    def test_odbijena_zakrpa_ne_ulazi_u_red(self, poslusnik, zad, mila):
        _predaj(zad, LOSA, mila)
        assert poslusnik.get(reverse("tasks-queued")).json()["data"]["tasks"] == []

    def test_zavrsen_zadatak_izlazi_iz_reda(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        with bind(actor_id="user:slobodan"):
            for g in zad.required_gates:
                zadaci.record_gate(zad, g, True)
            zadaci.finish(zad)
        assert poslusnik.get(reverse("tasks-queued")).json()["data"]["tasks"] == []

    def test_red_vraca_samo_identifikatore(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        podaci = poslusnik.get(reverse("tasks-queued")).json()["data"]
        assert list(podaci) == ["tasks"]
        assert all(isinstance(t, str) for t in podaci["tasks"])


class TestRad:
    def test_izdaje_prihvacenu_zakrpu(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        podaci = poslusnik.get(
            reverse("task-work", args=[zad.public_id])).json()["data"]
        assert podaci["diff"] == DIFF and podaci["base_sha"] == "9f65d41"
        assert podaci["paths"] == ["apps/content/steps.py"]

    def test_odbijena_zakrpa_se_ne_izdaje(self, poslusnik, zad, mila):
        _predaj(zad, LOSA, mila)
        assert poslusnik.get(
            reverse("task-work", args=[zad.public_id])).status_code == 404

    def test_nepostojeci_zadatak(self, poslusnik, db):
        assert poslusnik.get(
            reverse("task-work", args=["TSK-01M3C15CJ999KE2FX8PG6KHMZE"])
        ).status_code == 404

    def test_neispravan_oblik_id(self, poslusnik, db):
        assert poslusnik.get(
            reverse("task-work", args=["nije-id"])).status_code == 404


class TestKapija:
    def test_upisuje_ishod(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        o = poslusnik.post(reverse("task-gate", args=[zad.public_id]),
                           {"gate": "pytest", "passed": True, "detail": "708 passed"},
                           format="json")
        assert o.status_code == 200
        assert o.json()["data"]["gates"]["pytest"] is True
        assert zad.gates.filter(gate="pytest", passed=True).exists()

    def test_svaki_pokusaj_ostaje(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        for prosla in (False, True):
            poslusnik.post(reverse("task-gate", args=[zad.public_id]),
                           {"gate": "ruff", "passed": prosla}, format="json")
        assert zad.gates.filter(gate="ruff").count() == 2

    def test_nepoznata_kapija(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        o = poslusnik.post(reverse("task-gate", args=[zad.public_id]),
                           {"gate": "izmisljena", "passed": True}, format="json")
        assert o.status_code == 400

    def test_poslusnik_ne_zatvara_zadatak(self, poslusnik, zad, mila):
        """Sve kapije zelene ne znače da je poslušnik završio posao."""
        _predaj(zad, DIFF, mila)
        for g in zad.required_gates:
            poslusnik.post(reverse("task-gate", args=[zad.public_id]),
                           {"gate": g, "passed": True}, format="json")
        zad.refresh_from_db()
        assert zad.status != E.TaskStatus.DONE

    def test_operater_takodje_sme(self, operater, zad, mila):
        """Tri tačke nisu rezervisane za poslušnika — čovek ih vidi kao i sve."""
        _predaj(zad, DIFF, mila)
        assert operater.get(reverse("tasks-queued")).status_code == 200


class TestNalog:
    def test_komanda_pise_token_u_fajl_a_ne_na_ekran(self, db, tmp_path):
        import io

        from django.core.management import call_command
        out = io.StringIO()
        put = tmp_path / "runner.env"
        call_command("poslusnik", "--napravi", "--u", str(put), stdout=out)
        sadrzaj = put.read_text(encoding="utf-8")
        assert sadrzaj.startswith("PERSONA_TOKEN=")
        kljuc = sadrzaj.split("=", 1)[1].strip()
        assert kljuc not in out.getvalue(), "ključ ne sme na ekran (ADR-0026)"
        assert kljuc[-4:] in out.getvalue()
        assert oct(put.stat().st_mode)[-3:] == "600"

    def test_nalog_nema_nijednu_canon_ulogu(self, db, tmp_path):
        from django.core.management import call_command
        call_command("poslusnik", "--napravi", "--u", str(tmp_path / "r.env"),
                     stdout=__import__("io").StringIO())
        u = User.objects.get(username="svc_runner")
        assert set(u.groups.values_list("name", flat=True)) == {RUNNER_GROUP}

    def test_bez_putanje_se_odbija(self, db):
        import io

        from django.core.management import CommandError, call_command
        with pytest.raises(CommandError, match="ne ispisuje"):
            call_command("poslusnik", "--napravi", stdout=io.StringIO())


class TestRedNeVrtiUKrug:
    """ADR-0040 — red drži NEMEREN posao.

    25.09. je poslušnik osam puta zaredom izmerio istu zakrpu, pola sata
    procesora, jer je red vraćao zadatke po statusu zadatka. Poslušnik namerno
    ne zatvara zadatak (ADR-0039 §3), pa nešto drugo mora da izbaci posao iz
    reda — i to je ishod merenja nad tom zakrpom.
    """

    def _izmeri(self, poslusnik, zad, patch_id, kapije=None):
        for g in (kapije or zad.required_gates):
            poslusnik.post(reverse("task-gate", args=[zad.public_id]),
                           {"gate": g, "passed": True, "patch": patch_id},
                           format="json")

    def _red(self, poslusnik):
        return poslusnik.get(reverse("tasks-queued")).json()["data"]["tasks"]

    def test_izmerena_zakrpa_izlazi_iz_reda(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        pid = poslusnik.get(
            reverse("task-work", args=[zad.public_id])).json()["data"]["patch_id"]
        assert self._red(poslusnik) == [zad.public_id]
        self._izmeri(poslusnik, zad, pid)
        assert self._red(poslusnik) == []

    def test_dovoljna_je_jedna_kapija(self, poslusnik, zad, mila):
        """Merenje je počelo — posao više nije nemeren, pa ne kruži."""
        _predaj(zad, DIFF, mila)
        pid = poslusnik.get(
            reverse("task-work", args=[zad.public_id])).json()["data"]["patch_id"]
        self._izmeri(poslusnik, zad, pid, kapije=["pytest"])
        assert self._red(poslusnik) == []

    def test_pale_kapije_takodje_izbacuju(self, poslusnik, zad, mila):
        """Neuspeh je ishod. Zadatak koji pada ne sme da se vrti u krug."""
        _predaj(zad, DIFF, mila)
        pid = poslusnik.get(
            reverse("task-work", args=[zad.public_id])).json()["data"]["patch_id"]
        poslusnik.post(reverse("task-gate", args=[zad.public_id]),
                       {"gate": "pytest", "passed": False, "patch": pid},
                       format="json")
        assert self._red(poslusnik) == []

    def test_nova_zakrpa_ponovo_ulazi(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        pid = poslusnik.get(
            reverse("task-work", args=[zad.public_id])).json()["data"]["patch_id"]
        self._izmeri(poslusnik, zad, pid)
        assert self._red(poslusnik) == []
        _predaj(zad, DIFF.replace("+b", "+c"), mila)
        assert self._red(poslusnik) == [zad.public_id]

    def test_work_izdaje_neizmerenu_zakrpu(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        pid = poslusnik.get(
            reverse("task-work", args=[zad.public_id])).json()["data"]["patch_id"]
        self._izmeri(poslusnik, zad, pid)
        assert poslusnik.get(
            reverse("task-work", args=[zad.public_id])).status_code == 404

    def test_tudja_zakrpa_se_odbija(self, poslusnik, zad, mila, db):
        """`patch` koji ne pripada zadatku ne sme da prođe."""
        _predaj(zad, DIFF, mila)
        import uuid
        o = poslusnik.post(reverse("task-gate", args=[zad.public_id]),
                           {"gate": "pytest", "passed": True,
                            "patch": str(uuid.uuid4())}, format="json")
        assert o.status_code == 404


class TestRezultat:
    """ADR-0043 — četvrta tačka: grana, i samo grana.

    Poslušnik i dalje ne zatvara zadatak. Sve što sme jeste da kaže gde je
    ostavio commit, i to tek pošto su kapije nad tom zakrpom zelene.
    """

    SHA = "c" * 40

    def _zeleno(self, poslusnik, zad, zk):
        for g in zad.required_gates:
            poslusnik.post(reverse("task-gate", args=[zad.public_id]),
                           {"gate": g, "passed": True, "patch": str(zk.pk)},
                           format="json")

    def test_work_nosi_granu_i_poruku(self, poslusnik, zad, mila):
        _predaj(zad, DIFF, mila)
        podaci = poslusnik.get(
            reverse("task-work", args=[zad.public_id])).json()["data"]
        assert podaci["branch"] == f"zadatak/{zad.public_id}"
        assert podaci["branch_expected_sha"] == ""
        assert podaci["author_email"].endswith("@agenti.webkorporacija.com")
        assert zad.public_id in podaci["commit_message"]

    def test_zeleno_upisuje_granu(self, poslusnik, zad, mila):
        zk = _predaj(zad, DIFF, mila)
        self._zeleno(poslusnik, zad, zk)
        odgovor = poslusnik.post(
            reverse("task-result", args=[zad.public_id]),
            {"patch": str(zk.pk), "branch": f"zadatak/{zad.public_id}",
             "commit": self.SHA}, format="json")
        assert odgovor.status_code == 200
        zad.refresh_from_db()
        assert zad.commit_sha == self.SHA
        assert zad.status != E.TaskStatus.DONE.value

    def test_bez_zelenih_kapija_se_odbija(self, poslusnik, zad, mila):
        zk = _predaj(zad, DIFF, mila)
        odgovor = poslusnik.post(
            reverse("task-result", args=[zad.public_id]),
            {"patch": str(zk.pk), "branch": f"zadatak/{zad.public_id}",
             "commit": self.SHA}, format="json")
        assert odgovor.status_code == 400

    def test_tudja_grana_se_odbija(self, poslusnik, zad, mila):
        zk = _predaj(zad, DIFF, mila)
        self._zeleno(poslusnik, zad, zk)
        assert poslusnik.post(
            reverse("task-result", args=[zad.public_id]),
            {"patch": str(zk.pk), "branch": "main", "commit": self.SHA},
            format="json").status_code == 400

    def test_tudja_zakrpa_se_odbija(self, poslusnik, zad, mila, db):
        with bind(actor_id="user:slobodan"):
            drugi = zadaci.create(title="Drugi", why="Drugi razlog.",
                                  allowed_paths=["apps/content"], assignee=mila)
        zk = _predaj(drugi, DIFF, mila)
        self._zeleno(poslusnik, drugi, zk)
        assert poslusnik.post(
            reverse("task-result", args=[zad.public_id]),
            {"patch": str(zk.pk), "branch": f"zadatak/{zad.public_id}",
             "commit": self.SHA}, format="json").status_code == 404

    def test_operater_takodje_sme(self, operater, zad, mila, poslusnik):
        zk = _predaj(zad, DIFF, mila)
        self._zeleno(poslusnik, zad, zk)
        assert operater.post(
            reverse("task-result", args=[zad.public_id]),
            {"patch": str(zk.pk), "branch": f"zadatak/{zad.public_id}",
             "commit": self.SHA}, format="json").status_code == 200

    def test_druga_zakrpa_nosi_ocekivanu_vrednost(self, poslusnik, zad, mila):
        """`--force-with-lease` dobija ono što aplikacija zna da na grani stoji."""
        zk = _predaj(zad, DIFF, mila)
        self._zeleno(poslusnik, zad, zk)
        poslusnik.post(reverse("task-result", args=[zad.public_id]),
                       {"patch": str(zk.pk), "branch": f"zadatak/{zad.public_id}",
                        "commit": self.SHA}, format="json")
        _predaj(zad, DIFF.replace("+b", "+c"), mila)
        podaci = poslusnik.get(
            reverse("task-work", args=[zad.public_id])).json()["data"]
        assert podaci["branch_expected_sha"] == self.SHA
