"""ADR-0020 — opsezi memorije i pečaćenje u nivoe.

  - tema ispod praga se ne dira; prepuna tema postaje sažetak nivoa 1;
  - izvori se arhiviraju, ne brišu, i vezani su za sažetak (`DERIVED`);
  - prekretnica (salience ≥ 0,80) i PINNED ostaju aktivni;
  - pečaćenje je idempotentno i ne zove model;
  - tema koja se ponavlja kod više agenata istog sektora postaje znanje sektora;
  - tema u više sektora postaje znanje firme;
  - agent u retrieval-u vidi svoje + svog sektora + firme, a **tuđe lične
    zapise nikada**.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from django.core.management import call_command

from api.context import bind
from apps.memory import retrieval, sealing
from apps.memory.models import MemoryItem, MemoryLink
from apps.memory.writer import MemoryInput, write
from apps.personas import org
from apps.personas.models import Persona, Position
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
NOW = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
S = E.MemoryScope


@pytest.fixture
def firma(mila):
    with bind(actor_id="user:slobodan"):
        call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())
    return Persona.objects.get(public_id="P-00001")


def _agent(pid: str, position: str, name: str = "Agent") -> Persona:
    p = Persona.objects.create(
        public_id=pid, slug=pid.lower(), display_name=f"{name} ({pid}) (AI)",
        persona_type=E.PersonaType.AI_CREATOR, status=E.PersonaStatus.READY,
        disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE, primary_locale="sr-Latn",
        timezone="Europe/Belgrade")
    with bind(actor_id="user:slobodan"):
        org.assign(p, Position.objects.get(code=position), actor="user:slobodan")
    return p


def _mem(persona, topic: str, n: int, *, salience: float = 0.5, start: int = 0):
    out = []
    with bind(actor_id="service:test"):
        for i in range(n):
            r = write(persona, MemoryInput(
                memory_type=E.MemoryType.SEMANTIC,
                title=f"{topic} zapis {start + i}",
                content=f"Nalaz o temi {topic}, broj {start + i}.",
                source_kind=E.SourceKind.SYSTEM_OBSERVATION,
                provenance=E.Provenance.OBSERVED, salience=salience,
                tags=[topic], source_event_id=f"t:{persona.public_id}:{topic}:{start + i}",
            ), now=NOW)
            if r.memory is not None:
                out.append(r.memory)
    return out


class TestPersonaSealing:
    def test_below_threshold_nothing_happens(self, firma):
        _mem(firma, "rokovi", 5)
        with bind(actor_id="service:memory"):
            assert sealing.seal_persona(firma, now=NOW) == []
        assert MemoryItem.objects.filter(persona=firma, level=1).count() == 0

    def test_full_topic_becomes_summary_and_sources_are_archived(self, firma):
        items = _mem(firma, "rokovi", 12)
        with bind(actor_id="service:memory"):
            made = sealing.seal_persona(firma, now=NOW)
        assert len(made) == 1
        s = made[0]
        assert s.level == 1 and s.scope == S.PERSONA and s.tags == ["rokovi"]
        assert "12 zapisa" in s.content and "rokovi" in s.title
        assert MemoryLink.objects.filter(from_memory=s,
                                         relation=E.MemoryRelation.DERIVED).count() == 12
        for m in items:
            m.refresh_from_db()
            assert m.status == E.MemoryStatus.ARCHIVED

    def test_milestone_and_pinned_stay_active(self, firma):
        _mem(firma, "rokovi", 11)
        veliki = _mem(firma, "rokovi", 1, salience=0.9, start=100)[0]
        pinned = _mem(firma, "rokovi", 1, start=200)[0]
        MemoryItem.objects.filter(pk=pinned.pk).update(status=E.MemoryStatus.PINNED.value)
        with bind(actor_id="service:memory"):
            sealing.seal_persona(firma, now=NOW)
        veliki.refresh_from_db()
        pinned.refresh_from_db()
        assert veliki.status == E.MemoryStatus.ACTIVE
        assert pinned.status == E.MemoryStatus.PINNED

    def test_sealing_is_idempotent(self, firma):
        _mem(firma, "rokovi", 12)
        with bind(actor_id="service:memory"):
            sealing.seal_persona(firma, now=NOW)
            sealing.seal_persona(firma, now=NOW)
        assert MemoryItem.objects.filter(persona=firma, level=1).count() == 1

    def test_no_model_call(self, firma, monkeypatch):
        from apps.llm_gateway import gateway

        def boom(*a, **k):  # pragma: no cover — sme da se ne pozove
            raise AssertionError("pečaćenje ne sme da zove model")

        monkeypatch.setattr(gateway, "generate", boom)
        _mem(firma, "rokovi", 12)
        with bind(actor_id="service:memory"):
            assert len(sealing.seal_persona(firma, now=NOW)) == 1


class TestCascade:
    def _five_agents_one_topic(self, firma):
        """Pet agenata istog sektora, svaki sa zapečaćenom temom „rokovi"."""
        people = [firma]
        for i in range(2, 6):
            Position.objects.create(
                department=org.department_of(firma), code=f"URE-{i}",
                title=f"Urednik {i}", level=E.OrgLevel.MEDIOR.value)
            people.append(_agent(f"P-0000{i}", f"URE-{i}"))
        with bind(actor_id="service:memory"):
            for p in people:
                _mem(p, "rokovi", 12)
                sealing.seal_persona(p, now=NOW)
        return people

    def test_topic_across_agents_becomes_department_knowledge(self, firma):
        self._five_agents_one_topic(firma)
        dep = org.department_of(firma)
        with bind(actor_id="service:memory"):
            made = sealing.seal_department(dep, now=NOW)
        assert len(made) == 1
        m = made[0]
        assert m.scope == S.DEPARTMENT and m.department_id == dep.pk
        assert "(department)" in m.title and "5 zapisa" in m.content

    def test_topic_across_departments_becomes_company_knowledge(self, firma):
        self._five_agents_one_topic(firma)
        with bind(actor_id="service:memory"):
            sealing.seal_department(org.department_of(firma), now=NOW)
            # isti postupak u drugom sektoru
            drugi = Persona.objects.create(
                public_id="P-00009", slug="p-00009", display_name="Podrška (AI)",
                persona_type=E.PersonaType.AI_CREATOR, status=E.PersonaStatus.READY,
                disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE, primary_locale="sr-Latn",
                timezone="Europe/Belgrade")
            org.assign(drugi, Position.objects.get(code="POD-SR"), actor="user:slobodan")
            _mem(drugi, "rokovi", 12)
            sealing.seal_persona(drugi, now=NOW)
            sealing.seal_department(org.position_of(drugi).department, now=NOW,
                                    threshold=1)
            made = sealing.seal_company(now=NOW, threshold=2)
        assert len(made) == 1 and made[0].scope == S.COMPANY
        assert made[0].department_id is None

    def test_company_needs_more_than_one_department(self, firma):
        self._five_agents_one_topic(firma)
        with bind(actor_id="service:memory"):
            sealing.seal_department(org.department_of(firma), now=NOW)
            assert sealing.seal_company(now=NOW, threshold=1) == []


class TestVisibility:
    def test_agent_sees_own_department_and_company_but_not_others(self, firma):
        drugi = _agent("P-00007", "POD-SR", "Podrška")
        _mem(firma, "rokovi", 3)
        tudje = _mem(drugi, "reklamacije", 3)

        dep = org.department_of(firma)
        with bind(actor_id="service:memory"):
            sektorska = write(firma, MemoryInput(
                memory_type=E.MemoryType.SEMANTIC, title="Sektorsko pravilo",
                content="U marketingu ne obećavamo rokove.",
                source_kind=E.SourceKind.SYSTEM_OBSERVATION,
                provenance=E.Provenance.OBSERVED, salience=0.7, tags=["rokovi"],
                source_event_id="sek:1"), now=NOW).memory
            MemoryItem.objects.filter(pk=sektorska.pk).update(
                scope=S.DEPARTMENT.value, department=dep, level=1)
            firmska = write(firma, MemoryInput(
                memory_type=E.MemoryType.SEMANTIC, title="Pravilo firme",
                content="Sve se plaća avansno.",
                source_kind=E.SourceKind.SYSTEM_OBSERVATION,
                provenance=E.Provenance.OBSERVED, salience=0.7, tags=["placanje"],
                source_event_id="fir:1"), now=NOW).memory
            MemoryItem.objects.filter(pk=firmska.pk).update(
                scope=S.COMPANY.value, level=2)

        vidi = {str(s.memory.id) for s in retrieval.retrieve(
            firma, "rokovi i plaćanje", E.RetrievalProfile.RESEARCH, now=NOW, top_k=50)}
        assert str(sektorska.pk) in vidi and str(firmska.pk) in vidi
        assert not {str(m.pk) for m in tudje} & vidi

        # drugi agent je u drugom sektoru: vidi firmsko, ne vidi marketinško
        njegovo = {str(s.memory.id) for s in retrieval.retrieve(
            drugi, "rokovi i plaćanje", E.RetrievalProfile.RESEARCH, now=NOW, top_k=50)}
        assert str(firmska.pk) in njegovo and str(sektorska.pk) not in njegovo

    def test_shared_memory_is_marked_in_context(self, firma):
        from apps.content.service import operator_run
        from apps.memory import context as memory_context

        with bind(actor_id="service:memory"):
            m = write(firma, MemoryInput(
                memory_type=E.MemoryType.SEMANTIC, title="Pravilo firme",
                content="Sve se plaća avansno.",
                source_kind=E.SourceKind.SYSTEM_OBSERVATION,
                provenance=E.Provenance.OBSERVED, salience=0.9, tags=["placanje"],
                source_event_id="fir:2"), now=NOW).memory
            MemoryItem.objects.filter(pk=m.pk).update(scope=S.COMPANY.value, level=2)
            run = operator_run(firma, NOW)
            pack = memory_context.build(firma, run, E.RetrievalProfile.RESEARCH,
                                        query="plaćanje", now=NOW)
        assert "znanje firme" in pack.text


class TestCounts:
    def test_counts_for_console(self, firma):
        _mem(firma, "rokovi", 12)
        with bind(actor_id="service:memory"):
            sealing.seal_persona(firma, now=NOW)
        c = sealing.counts(firma)
        assert c["sažeci"] == 1 and c["sektor"] == 0 and c["firma"] == 0
