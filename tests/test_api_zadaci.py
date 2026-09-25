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
