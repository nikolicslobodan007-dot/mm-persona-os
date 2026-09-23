"""ADR-0017 — korporativna organizacija i dosije agenta.

  - sektori i radna mesta iz `seed_org`, idempotentno;
  - raspored zatvara prethodni i poštuje broj izvršilaca;
  - lanac odgovornosti se ne vrti u krug i niko ne odobrava sam sebi;
  - dosije je modelovan: bez maloletnih, mere u granicama, svaka izmena verzija;
  - radno mesto ulazi u prompt, a visina i težina ne;
  - pouka može da važi za ceo sektor;
  - odgovor na poštu od sada uvek traži odobrenje.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime

import pytest
from django.core.management import call_command

from api.context import bind
from apps.personas import org
from apps.personas.models import Assignment, Department, Persona, Position
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
NOW = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)


@pytest.fixture
def firma(mila):
    with bind(actor_id="user:slobodan"):
        call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
    return Persona.objects.get(public_id="P-00001")


def _second(name="Jovan Ilić (AI)", pid="P-00002"):
    return Persona.objects.create(
        public_id=pid, slug=pid.lower(), display_name=name,
        persona_type=E.PersonaType.AI_CREATOR, status=E.PersonaStatus.READY,
        disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE, primary_locale="sr-Latn",
        timezone="Europe/Belgrade")


class TestSeed:
    def test_departments_positions_and_assignment(self, firma):
        assert Department.objects.count() == 9
        assert Department.objects.get(code="MARKETING").name == "Marketing i sadržaj"
        pos = org.position_of(firma)
        assert pos.code == "URE-SR" and pos.department.code == "MARKETING"
        assert pos.reports_to.code == "SEF-MKT"

    def test_seed_is_idempotent(self, firma):
        with bind(actor_id="user:slobodan"):
            call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
        assert Department.objects.count() == 9
        assert Assignment.objects.filter(persona=firma, ended_at__isnull=True).count() == 1

    def test_position_gives_no_permission(self, firma):
        """Radno mesto nije dozvola: poverenje ostaje tamo gde ga je policy dala."""
        assert firma.trust_level == E.TrustLevel.L0


class TestAssignment:
    def test_move_closes_previous(self, firma):
        old = Assignment.objects.get(persona=firma, ended_at__isnull=True)
        with bind(actor_id="user:slobodan"):
            org.assign(firma, Position.objects.get(code="SEF-MKT"), actor="user:slobodan")
        old.refresh_from_db()
        assert old.ended_at is not None
        assert org.position_of(firma).code == "SEF-MKT"
        assert Assignment.objects.filter(persona=firma, ended_at__isnull=True).count() == 1

    def test_headcount_is_respected(self, firma):
        other = _second()
        pos = Position.objects.get(code="URE-SR")  # headcount_max = 1, zauzeto
        with bind(actor_id="user:slobodan"), pytest.raises(org.OrgError) as e:
            org.assign(other, pos, actor="user:slobodan")
        assert e.value.code == "VALIDATION_ERROR"


class TestChain:
    def test_manager_and_escalation_to_human(self, firma):
        assert org.manager_of(firma) is None          # šef marketinga nije popunjen
        assert org.escalation_target(firma) == "user:slobodan"

    def test_manager_found_when_seat_is_filled(self, firma):
        boss = _second()
        with bind(actor_id="user:slobodan"):
            org.assign(boss, Position.objects.get(code="SEF-MKT"), actor="user:slobodan")
        assert org.manager_of(firma).public_id == boss.public_id
        assert org.escalation_target(firma) == boss.public_id
        assert [p.public_id for p in org.chain_of_command(firma)] == [boss.public_id]

    def test_nobody_approves_themselves(self, firma):
        """Agent koji sedi i na svom i na šefovskom mestu nije sam sebi šef."""
        with bind(actor_id="user:slobodan"):
            org.assign(firma, Position.objects.get(code="SEF-MKT"), actor="user:slobodan")
        assert org.manager_of(firma) is None
        assert firma not in org.chain_of_command(firma)


class TestDossier:
    def test_minor_is_refused(self, firma):
        with bind(actor_id="user:slobodan"), pytest.raises(org.OrgError) as e:
            org.set_dossier(firma, actor="user:slobodan", birth_date=date(2015, 1, 1),
                            now=NOW)
        assert e.value.code == "VALIDATION_ERROR"

    def test_change_bumps_version_and_audits(self, firma):
        from apps.observability.models import AuditEvent

        before = org.dossier_of(firma).dossier_version
        with bind(actor_id="user:slobodan"):
            org.set_dossier(firma, actor="user:slobodan", residence="Novi Sad", now=NOW)
        d = org.dossier_of(firma)
        assert d.residence == "Novi Sad" and d.dossier_version == before + 1
        assert AuditEvent.objects.filter(event_key="persona.dossier.changed").exists()

    def test_unknown_field_refused(self, firma):
        with bind(actor_id="user:slobodan"), pytest.raises(org.OrgError):
            org.set_dossier(firma, actor="user:slobodan", jmbg="1234567890123", now=NOW)

    def test_measures_out_of_range_are_refused_by_db(self, firma):
        from django.db.utils import IntegrityError

        with bind(actor_id="user:slobodan"), pytest.raises(IntegrityError):
            org.set_dossier(firma, actor="user:slobodan", height_cm=15, now=NOW)


class TestPrompt:
    def test_position_in_prompt_measures_not(self, firma):
        text = org.prompt_section(firma, now=NOW)
        assert "Marketing i sadržaj" in text and "Urednik sadržaja" in text
        assert "172" not in text and "63" not in text
        assert "35 godina" in text and "Novi Sad" in text

    def test_no_assignment_no_section(self, mila):
        assert org.prompt_section(_second(), now=NOW) == ""


class TestSectorLessons:
    def test_sector_rule_reaches_only_that_sector(self, firma):
        from apps.content import lessons

        dep = org.department_of(firma)
        with bind(actor_id="user:slobodan"):
            lessons.learn(persona=firma, kind="manual", actor="user:slobodan",
                          reason="U sektoru marketinga ne obećavamo rokove.", department=dep)
        assert "ne obećavamo rokove" in lessons.prompt_section(firma)
        assert "[MARKETING]" in lessons.prompt_section(firma)

        drugi = _second()
        with bind(actor_id="user:slobodan"):
            org.assign(drugi, Position.objects.get(code="POD-SR"), actor="user:slobodan")
        assert "ne obećavamo rokove" not in lessons.prompt_section(drugi)

    def test_everyone_beats_sector(self, firma):
        from apps.content import lessons

        with bind(actor_id="user:slobodan"):
            lesson = lessons.learn(persona=firma, kind="manual", actor="user:slobodan",
                                   reason="Srpske navodnice.", everyone=True,
                                   department=org.department_of(firma))
        assert lesson.persona_id is None and lesson.department_id is None
