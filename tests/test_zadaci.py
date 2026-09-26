"""ADR-0035 — model zadatka.

Šta se ovde brani:

  - zadatak bez spiska putanja se ne pravi; zaštićena zona u spisku ga obara;
  - `may_touch` propušta samo ono što prođe sve tri provere;
  - dodela pada ako agent nema poverenje na SVAKOJ dozvoljenoj putanji;
  - recenzent nije autor — i to drži baza, ne samo servis;
  - gotovo je merenje: `finish()` odbija dok kapije nisu zelene.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction

from api.context import bind
from apps.orchestration import zadaci
from apps.orchestration.models import CodeTask
from apps.personas.models import Persona
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]


@pytest.fixture
def drugi(mila):
    """Druga persona — za recenzenta, jer autor ne recenzira sebe."""
    return Persona.objects.create(
        public_id="P-09001", display_name="Recenzent",
        persona_type=E.PersonaType.ASSISTANT, status=E.PersonaStatus.ACTIVE,
    )


def _poverenje(p, nivo, opseg=""):
    with bind(actor_id="user:slobodan"):
        policy.change_trust(p, "code.write", nivo, actor="user:slobodan",
                            reason="proba", scope=opseg)


def _zadatak(**kw):
    with bind(actor_id="user:slobodan"):
        kw.setdefault("title", "Srpski navodnici u nacrtu")
        kw.setdefault("why", "Marketing javlja da nacrt gubi navodnike.")
        kw.setdefault("allowed_paths", ["apps/content"])
        return zadaci.create(**kw)


class TestPravljenje:
    def test_bez_putanja_se_ne_pravi(self, db):
        with pytest.raises(zadaci.TaskError) as e:
            _zadatak(allowed_paths=[])
        assert e.value.code == "NO_PATHS"
        assert not CodeTask.objects.exists()

    def test_zasticena_zona_obara_zadatak(self, db):
        with pytest.raises(zadaci.TaskError) as e:
            _zadatak(allowed_paths=["apps/content", "apps/policy"])
        assert e.value.code == "PROTECTED_PATH"
        assert not CodeTask.objects.exists()

    def test_bez_razloga_se_ne_pravi(self, db):
        with pytest.raises(zadaci.TaskError) as e:
            _zadatak(why="   ")
        assert e.value.code == "NO_REASON"

    def test_putanje_se_normalizuju_i_ne_dupliraju(self, db):
        z = _zadatak(allowed_paths=["./apps/content", "apps\\content", "tests/"])
        assert z.allowed_paths == ["apps/content", "tests/"]

    def test_podrazumevane_kapije(self, db):
        z = _zadatak()
        assert z.required_gates == list(E.DEFAULT_GATES)
        assert "review" not in z.required_gates

    def test_nepoznata_kapija(self, db):
        with pytest.raises(zadaci.TaskError) as e:
            _zadatak(gates=["pytest", "izmisljena"])
        assert e.value.code == "UNKNOWN_GATE"

    def test_public_id_je_TSK(self, db):
        assert _zadatak().public_id.startswith("TSK-")


class TestDodela:
    def test_bez_poverenja_nema_dodele(self, mila):
        z = _zadatak()
        with pytest.raises(zadaci.TaskError) as e:
            zadaci.assign(z, assignee=mila)
        assert e.value.code == "TRUST_TOO_LOW"
        z.refresh_from_db()
        assert z.assignee_id is None

    def test_poverenje_mora_da_pokrije_svaku_putanju(self, mila):
        _poverenje(mila, E.TrustLevel.L1, opseg="apps/content")
        z = _zadatak(allowed_paths=["apps/content", "apps/channels"])
        with pytest.raises(zadaci.TaskError) as e:
            zadaci.assign(z, assignee=mila)
        assert "apps/channels" in str(e.value)

    def test_dodela_prolazi_kad_poverenje_pokriva(self, mila):
        _poverenje(mila, E.TrustLevel.L1, opseg="apps/content")
        z = _zadatak()
        with bind(actor_id="user:slobodan"):
            zadaci.assign(z, assignee=mila)
        z.refresh_from_db()
        assert z.assignee_id == mila.pk and z.status == E.TaskStatus.ASSIGNED

    def test_recenzent_nije_autor(self, mila):
        _poverenje(mila, E.TrustLevel.L1, opseg="apps/content")
        z = _zadatak()
        with pytest.raises(zadaci.TaskError) as e, bind(actor_id="user:slobodan"):
            zadaci.assign(z, assignee=mila, reviewer=mila)
        assert e.value.code == "SELF_REVIEW"

    def test_bazu_ne_zaobilazi_ni_direktan_upis(self, mila):
        """Servis se zaobilazi jednim `objects.create` — zato ograničenje stoji u bazi."""
        with pytest.raises(IntegrityError), transaction.atomic():
            CodeTask.objects.create(
                public_id="TSK-01M3AW21XJP69X0X7YH2VW05E1", title="x", why="y",
                allowed_paths=["apps/content"], assignee=mila, reviewer=mila,
            )


class TestGranica:
    @pytest.fixture
    def spreman(self, mila):
        _poverenje(mila, E.TrustLevel.L1, opseg="apps/content")
        z = _zadatak()
        with bind(actor_id="user:slobodan"):
            zadaci.assign(z, assignee=mila)
        return z

    def test_dozvoljena_putanja(self, spreman):
        assert zadaci.may_touch(spreman, "apps/content/steps.py") is None

    def test_van_zadatka(self, spreman):
        assert "van dozvoljenih" in zadaci.may_touch(spreman, "apps/memory/writer.py")

    def test_zasticena_zona_i_kad_je_poverenje_visoko(self, spreman, mila):
        _poverenje(mila, E.TrustLevel.L2)
        assert "zaštićena zona" in zadaci.may_touch(spreman, "apps/policy/service.py")

    def test_prefiks_ne_hvata_slicno_ime(self, spreman):
        """`apps/content` ne sme da otvori `apps/contentx`."""
        assert zadaci.may_touch(spreman, "apps/contentx/steps.py") is not None

    def test_poverenje_skinuto_zatvara_putanju(self, spreman, mila):
        _poverenje(mila, E.TrustLevel.L0, opseg="apps/content")
        assert "poverenje L0" in zadaci.may_touch(spreman, "apps/content/steps.py")


class TestKapije:
    @pytest.fixture
    def z(self, mila):
        _poverenje(mila, E.TrustLevel.L1, opseg="apps/content")
        t = _zadatak()
        with bind(actor_id="user:slobodan"):
            zadaci.assign(t, assignee=mila)
        return t

    def _sve_zelene(self, z):
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)

    def test_bez_kapija_nije_gotovo(self, z):
        with pytest.raises(zadaci.TaskError) as e, bind(actor_id="user:slobodan"):
            zadaci.finish(z)
        assert e.value.code == "GATES_NOT_GREEN"
        assert "nije vrtena" in str(e.value)

    def test_pala_kapija_drzi_zadatak(self, z):
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, g != "ruff")
            with pytest.raises(zadaci.TaskError) as e:
                zadaci.finish(z)
        assert "ruff" in str(e.value)

    def test_sve_zelene_zatvaraju(self, z):
        self._sve_zelene(z)
        with bind(actor_id="user:slobodan"):
            zadaci.finish(z, commit_sha="9f65d41")
        z.refresh_from_db()
        assert z.status == E.TaskStatus.DONE and z.commit_sha == "9f65d41"
        assert z.finished_at is not None

    def test_istorija_pokusaja_ostaje(self, z):
        """Bez istorije nema mere „prošla iz prvog puta" (ADR-0034 §6)."""
        with bind(actor_id="user:slobodan"):
            zadaci.record_gate(z, "pytest", False, detail="2 failed")
            zadaci.record_gate(z, "pytest", True)
        assert z.gates.filter(gate="pytest").count() == 2
        assert zadaci.gate_report(z)["pytest"] is True

    def test_nepoznata_kapija_se_ne_upisuje(self, z):
        with pytest.raises(zadaci.TaskError), bind(actor_id="user:slobodan"):
            zadaci.record_gate(z, "izmisljena", True)


class TestNalazi:
    @pytest.fixture
    def z(self, mila, drugi):
        _poverenje(mila, E.TrustLevel.L1, opseg="apps/content")
        t = _zadatak()
        with bind(actor_id="user:slobodan"):
            zadaci.assign(t, assignee=mila, reviewer=drugi)
        return t

    def test_autor_ne_recenzira_sebe(self, z, mila):
        with pytest.raises(zadaci.TaskError) as e, bind(actor_id="user:slobodan"):
            zadaci.add_finding(z, reviewer=mila, file="apps/content/steps.py",
                               claim="ovo je super", severity="NIT")
        assert e.value.code == "SELF_REVIEW"

    def test_blocker_drzi_zadatak_i_kad_su_kapije_zelene(self, z, drugi):
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)
            zadaci.add_finding(z, reviewer=drugi, file="apps/content/steps.py",
                               line=40, claim="gubi se navodnik na kraju",
                               severity="BLOCKER", source=zadaci.IZVOR_COVEK)
            with pytest.raises(zadaci.TaskError) as e:
                zadaci.finish(z)
        assert e.value.code == "OPEN_BLOCKERS"

    def test_zatvoren_blocker_pusta_zadatak(self, z, drugi):
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)
            n = zadaci.add_finding(z, reviewer=drugi, file="apps/content/steps.py",
                                   claim="gubi se navodnik", severity="BLOCKER",
                                   source=zadaci.IZVOR_COVEK)
            n.status = E.FindingStatus.FIXED
            n.save(update_fields=["status"])
            zadaci.finish(z)
        z.refresh_from_db()
        assert z.status == E.TaskStatus.DONE

    def test_manji_nalaz_ne_zadrzava(self, z, drugi):
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)
            zadaci.add_finding(z, reviewer=drugi, file="apps/content/steps.py",
                               claim="ime promenljive", severity="NIT")
            zadaci.finish(z)
        z.refresh_from_db()
        assert z.status == E.TaskStatus.DONE

    def test_prazna_tvrdnja(self, z, drugi):
        with pytest.raises(zadaci.TaskError), bind(actor_id="user:slobodan"):
            zadaci.add_finding(z, reviewer=drugi, file="x.py", claim="  ",
                               severity="MAJOR")


class TestKomanda:
    def test_novi_i_pregled(self, mila):
        out = io.StringIO()
        call_command("zadatak", "--novi", "--naslov", "Navodnici",
                     "--zasto", "Marketing javlja da nacrt gubi navodnike.",
                     "--putanje", "apps/content,tests/test_content.py",
                     "--adr", "0024", stdout=out)
        pid = out.getvalue().split()[0]
        assert pid.startswith("TSK-")
        out = io.StringIO()
        call_command("zadatak", "--zadatak", pid, stdout=out)
        assert "nije vrtena" in out.getvalue() and "apps/content" in out.getvalue()

    def test_zasticena_zona_iz_komande(self, db):
        with pytest.raises(CommandError, match="PROTECTED_PATH"):
            call_command("zadatak", "--novi", "--naslov", "x", "--zasto", "y",
                         "--putanje", "apps/policy", stdout=io.StringIO())

    def test_sme_i_ne_sme(self, mila):
        _poverenje(mila, E.TrustLevel.L1, opseg="apps/content")
        z = _zadatak()
        with bind(actor_id="user:slobodan"):
            zadaci.assign(z, assignee=mila)
        out = io.StringIO()
        call_command("zadatak", "--zadatak", z.public_id,
                     "--sme", "apps/content/steps.py", stdout=out)
        assert "sme" in out.getvalue()
        out = io.StringIO()
        call_command("zadatak", "--zadatak", z.public_id,
                     "--sme", "apps/policy/service.py", stdout=out)
        assert "ne sme" in out.getvalue()

    def test_zavrsi_odbija_dok_kapije_nisu_zelene(self, mila):
        z = _zadatak()
        with pytest.raises(CommandError, match="GATES_NOT_GREEN"):
            call_command("zadatak", "--zadatak", z.public_id, "--zavrsi",
                         stdout=io.StringIO())

    def test_kapija_trazi_tacno_jedan_ishod(self, mila):
        z = _zadatak()
        with pytest.raises(CommandError, match="tačno jedno"):
            call_command("zadatak", "--zadatak", z.public_id, "--kapija", "pytest",
                         "--prosla", "--pala", stdout=io.StringIO())
