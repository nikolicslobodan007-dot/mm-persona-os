"""F4 — Memory & Knowledge. ADR-0006.

Prati Memory v0.1 §20 i Definition of Done §21.1: idempotentnost, supersesija,
protivrečnosti bez izmišljenog pobednika, izolacija persona, osetljivost po
svrsi, bleđenje, konsolidacija sa lozom, tvrdi plafon tokena, brisanje sa
propagacijom i zlatni skup kao regresiona kapija.
"""

from __future__ import annotations

import io
import math
from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.management import call_command

from apps.behaviour import service, world
from apps.memory import context, embeddings, lifecycle, retrieval
from apps.memory.management.commands.memory_eval import run_eval
from apps.memory.models import (
    MemoryContextPack,
    MemoryContradiction,
    MemoryEmbedding,
    MemoryItem,
    MemoryLink,
)
from apps.memory.writer import MemoryInput, MemoryRejected, write
from apps.observability.models import EventOutbox
from apps.orchestration.models import AgentRun
from apps.personas.models import Persona
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def _m(content, **kw):
    kw.setdefault("memory_type", E.MemoryType.SEMANTIC)
    kw.setdefault("source_kind", E.SourceKind.SYSTEM_OBSERVATION)
    kw.setdefault("provenance", E.Provenance.OBSERVED)
    kw.setdefault("salience", 0.7)
    return MemoryInput(content=content, **kw)


@pytest.fixture
def mila(db):
    call_command("seed_agent_001", stdout=io.StringIO())
    return Persona.objects.get(public_id="P-00001")


@pytest.fixture
def other(mila):
    return Persona.objects.create(
        public_id="P-00002", slug="p2", display_name="Druga (AI)",
        persona_type=mila.persona_type, status=mila.status,
        runtime_environment=mila.runtime_environment, trust_level=mila.trust_level,
        disclosure_mode=mila.disclosure_mode, disclosure_required=True,
        primary_locale="sr-Latn-RS", timezone="Europe/Belgrade",
    )


def _run(p):
    return service.wake(p, E.WakePriority.OPERATOR_TASK, now=NOW)


# ---------------------------------------------------------------- embedding


class TestEmbeddings:
    def test_normalize_folds_diacritics(self):
        assert embeddings.normalize("Đak čita ŠĆŽ") == "djak cita scz"

    def test_same_root_closer_than_unrelated(self):
        a = embeddings.embed("logistika i transport")
        b = embeddings.embed("o logistici u transportu")
        c = embeddings.embed("recept za kolače")
        assert embeddings.cosine(a, b) > embeddings.cosine(a, c) + 0.2

    def test_deterministic_and_unit_length(self):
        v = embeddings.embed("isti tekst")
        assert v == embeddings.embed("isti tekst")
        assert math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-6)


# ---------------------------------------------------------------- writer


@pytest.mark.django_db
class TestWriter:
    def test_secret_material_refused(self, mila):
        with pytest.raises(MemoryRejected) as e:
            write(mila, _m("Pristup: password: hunter2hunter2"))
        assert e.value.code == "SECRET_MATERIAL"

    def test_provenance_must_match_source(self, mila):
        with pytest.raises(MemoryRejected):
            write(mila, _m("x", source_kind=E.SourceKind.LLM_INFERENCE,
                           provenance=E.Provenance.OBSERVED))

    def test_inferred_biography_refused(self, mila):
        with pytest.raises(MemoryRejected) as e:
            write(mila, _m("Mila voli planinarenje", source_kind=E.SourceKind.LLM_INFERENCE,
                           provenance=E.Provenance.INFERRED,
                           assertion=("P-00001", "hobby", "planinarenje")))
        assert e.value.code == "INFERRED_BIOGRAPHY"

    def test_low_eligibility_not_stored(self, mila):
        res = write(mila, _m("sitnica", memory_type=E.MemoryType.EPISODIC, salience=0.0,
                             novelty=0.0, future_utility=0.0, confidence=None, sensitivity=1.0))
        assert res.outcome == "rejected" and res.memory is None

    def test_same_source_event_five_times_one_record(self, mila):
        for _ in range(5):
            write(mila, _m("Objava je dobila 140 reakcija", memory_type=E.MemoryType.EPISODIC,
                           source_event_id="evt-140"))
        assert MemoryItem.objects.filter(persona=mila, source_event_id="evt-140").count() == 1

    def test_same_content_reinforces(self, mila):
        a = write(mila, _m("Kupci traže rok isporuke", confidence=0.95))
        b = write(mila, _m("Kupci traže  rok isporuke!", confidence=0.95))
        assert b.outcome == "reinforced" and a.memory.pk == b.memory.pk
        assert a.memory.sources.count() == 2

    def test_working_memory_expires_in_six_hours(self, mila):
        res = write(mila, _m("odgovori na 3 komentara", memory_type=E.MemoryType.WORKING), now=NOW)
        assert res.memory.expires_at == NOW + timedelta(hours=6)

    def test_every_memory_gets_vector(self, mila):
        res = write(mila, _m("Nova činjenica o tržištu"))
        emb = MemoryEmbedding.objects.get(memory=res.memory)
        assert emb.model_key == embeddings.model_key() and emb.text_hash


@pytest.mark.django_db
class TestContradictions:
    CLAIM = ("P-00001", "posts_per_week", 4)

    def test_equal_or_stronger_supersedes(self, mila):
        old = write(mila, _m("Objavljuje 4x nedeljno", assertion=self.CLAIM)).memory
        res = write(mila, _m("Objavljuje 2x nedeljno", assertion=("P-00001", "posts_per_week", 2)))
        old.refresh_from_db()
        assert old.status == E.MemoryStatus.SUPERSEDED and old.superseded_by == res.memory
        assert old.valid_to is not None
        assert MemoryLink.objects.filter(from_memory=res.memory, to_memory=old,
                                         relation="supersedes").exists()
        assert MemoryContradiction.objects.get(left=old).status == "RESOLVED"
        assert EventOutbox.objects.filter(event_type="memory.contradiction_detected").exists()

    def test_weaker_evidence_keeps_both_and_flags(self, mila):
        write(mila, _m("Objavljuje 4x nedeljno", assertion=self.CLAIM, confidence=0.95))
        weak = write(mila, _m("Možda objavljuje 7x", source_kind=E.SourceKind.LLM_INFERENCE,
                              provenance=E.Provenance.INFERRED, confidence=0.3,
                              assertion=("P-00002", "posts_per_week", 7)))
        assert weak.outcome == "created"  # drugi subjekat — nema sukoba
        weak2 = write(mila, _m("Po proceni 7x nedeljno", source_kind=E.SourceKind.PUBLIC_WEB_SOURCE,
                               confidence=0.6, assertion=("P-00001", "posts_per_week", 7)))
        assert weak2.contradictions[0].status == "OPEN"
        active = MemoryItem.objects.filter(persona=mila, assertion_predicate="posts_per_week",
                                           assertion_subject="P-00001", status="ACTIVE")
        assert active.count() == 2
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="koliko puta nedeljno objavljuje", now=NOW)
        assert "⚠ sporno" in pack.text

    def test_pinned_is_never_superseded_automatically(self, mila):
        old = write(mila, _m("Objavljuje 4x", assertion=self.CLAIM,
                             status=E.MemoryStatus.PINNED)).memory
        write(mila, _m("Objavljuje 3x", assertion=("P-00001", "posts_per_week", 3)))
        old.refresh_from_db()
        assert old.status == E.MemoryStatus.PINNED

    def test_same_value_reinforces_not_duplicates(self, mila):
        a = write(mila, _m("Četiri puta nedeljno", assertion=self.CLAIM))
        b = write(mila, _m("Objavljuje 4 puta sedmično", assertion=self.CLAIM))
        assert b.outcome == "reinforced" and b.memory.pk == a.memory.pk


# ---------------------------------------------------------------- retrieval


@pytest.mark.django_db
class TestRetrieval:
    def test_persona_isolation(self, mila, other):
        write(other, _m("Tajna tuđe persone o logistici"))
        got = retrieval.retrieve(mila, "logistika", E.RetrievalProfile.RESEARCH, now=NOW)
        assert all(s.memory.persona_id == mila.pk for s in got)

    def test_superseded_never_returned(self, mila):
        old = write(mila, _m("Stari broj objava", assertion=("P-00001", "x", 1))).memory
        write(mila, _m("Novi broj objava", assertion=("P-00001", "x", 2)))
        got = retrieval.retrieve(mila, "broj objava", E.RetrievalProfile.RESEARCH, now=NOW)
        assert old.pk not in {s.memory.pk for s in got}

    def test_sensitive_only_for_allowed_purpose(self, mila):
        sens = write(mila, _m("Osetljiv podatak o ugovoru", sensitivity=0.9, salience=1.0,
                              goal_relevance=1.0, novelty=1.0)).memory
        planning = retrieval.retrieve(mila, "ugovor", E.RetrievalProfile.DAILY_PLANNER, now=NOW)
        summary = retrieval.retrieve(mila, "ugovor", E.RetrievalProfile.REFLECTION, now=NOW)
        assert sens.pk not in {s.memory.pk for s in planning}
        assert sens.pk in {s.memory.pk for s in summary}

    def test_breakdown_is_explained(self, mila):
        write(mila, _m("Kupci u građevini pitaju za rok isporuke"))
        top = retrieval.retrieve(mila, "rok isporuke građevina", E.RetrievalProfile.RESEARCH,
                                 now=NOW)[0]
        assert set(retrieval.WEIGHTS) <= set(top.breakdown)
        assert top.breakdown["task_relevance"] > 0 and top.breakdown["semantic"] > 0

    def test_decay_follows_half_life(self, mila):
        m = write(mila, _m("epizoda", memory_type=E.MemoryType.EPISODIC, salience=0.8),
                  now=NOW).memory
        later = NOW + timedelta(days=30)
        assert math.isclose(retrieval.effective_salience(m, later), 0.4, rel_tol=0.01)
        m.status = E.MemoryStatus.PINNED
        assert retrieval.effective_salience(m, later) == 0.8

    def test_works_without_vectors(self, mila):
        write(mila, _m("Hladni lanac za lekove"))
        MemoryEmbedding.objects.all().delete()
        got = retrieval.retrieve(mila, "lekovi hladni lanac", E.RetrievalProfile.RESEARCH, now=NOW)
        assert got and got[0].breakdown["semantic"] == 0.0

    def test_golden_suite_gate(self, db):
        """Canon §21 — mera za izbor modela; ovde i kapija protiv regresije."""
        r = run_eval(k=5)
        assert r["hit_at_k"] >= 0.9, r["misses"]


# ---------------------------------------------------------------- context


@pytest.mark.django_db
class TestContext:
    def test_hard_token_cap(self, mila):
        for i in range(60):
            write(mila, _m(f"Činjenica {i} o logistici i transportu " + "reč " * 40,
                           source_event_id=f"cap-{i}"))
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="logistika", max_tokens=900, now=NOW)
        assert pack.record.token_count <= 900
        assert pack.record.truncated is True
        assert pack.record.memory_ids == [str(s.memory.id) for s in pack.items]

    def test_pack_is_audited_and_counts_recall(self, mila):
        m = write(mila, _m("Kratka analiza plus tri saveta radi najbolje")).memory
        run = _run(mila)
        pack = context.build(mila, run, E.RetrievalProfile.CONTENT_CREATION,
                             query="format objave saveti", now=NOW)
        assert MemoryContextPack.objects.filter(run=run).count() == 1
        assert str(m.id) in pack.record.memory_ids
        m.refresh_from_db()
        assert m.recall_count == 1
        assert "AI persona" in pack.sections["persona_core"]
        assert EventOutbox.objects.filter(event_type="context.built").exists()

    def test_inferred_is_labelled(self, mila):
        write(mila, _m("Publika verovatno voli grafikone", source_kind=E.SourceKind.LLM_INFERENCE,
                       provenance=E.Provenance.INFERRED, salience=0.9, goal_relevance=0.9))
        pack = context.build(mila, _run(mila), E.RetrievalProfile.CONTENT_CREATION,
                             query="publika grafikoni", now=NOW)
        assert "izvod, ne činjenica" in pack.text


# ---------------------------------------------------------------- lifecycle


@pytest.mark.django_db
class TestLifecycle:
    def test_daily_consolidation_keeps_lineage(self, mila):
        day = date(2026, 9, 21)
        low = [write(mila, _m(f"Sitna epizoda {i}", memory_type=E.MemoryType.EPISODIC,
                              salience=0.4, tags=["logistics"], source_event_id=f"ep-{i}",
                              event_time=NOW + timedelta(minutes=i))).memory for i in range(4)]
        big = write(mila, _m("Prekretnica: prvi pilot ugovoren",
                             memory_type=E.MemoryType.EPISODIC, salience=0.9,
                             event_time=NOW)).memory
        summary = lifecycle.consolidate_day(mila, day, now=NOW + timedelta(days=1))
        assert summary is not None and summary.title == "Dan 2026-09-21"
        linked = set(MemoryLink.objects.filter(from_memory=summary, relation="derived")
                     .values_list("to_memory_id", flat=True))
        assert linked == {m.pk for m in low} | {big.pk}
        assert all(MemoryItem.objects.get(pk=m.pk).status == "ARCHIVED" for m in low)
        assert MemoryItem.objects.get(pk=big.pk).status == "ACTIVE"
        again = lifecycle.consolidate_day(mila, day, now=NOW + timedelta(days=1))
        assert again.pk == summary.pk
        assert MemoryItem.objects.filter(title="Dan 2026-09-21").count() == 1

    def test_working_memory_expires(self, mila):
        write(mila, _m("privremeno", memory_type=E.MemoryType.WORKING), now=NOW)
        assert lifecycle.expire_working(mila, NOW + timedelta(hours=7)) == 1

    def test_decay_archives_faded(self, mila):
        m = write(mila, _m("stara epizoda", memory_type=E.MemoryType.EPISODIC, salience=0.3),
                  now=NOW).memory
        assert lifecycle.apply_decay(mila, NOW + timedelta(days=200)) >= 1
        m.refresh_from_db()
        assert m.status == "ARCHIVED"

    def test_forget_propagates(self, mila):
        a = write(mila, _m("Za brisanje")).memory
        b = write(mila, _m("Druga", assertion=("P-00001", "k", 1))).memory
        MemoryLink.objects.create(from_memory=b, to_memory=a, relation="related")
        lifecycle.forget(a, reason="zahtev za brisanje")
        a.refresh_from_db()
        assert a.status == "DELETED" and "obrisano" in a.content
        assert not MemoryEmbedding.objects.filter(memory=a).exists()
        assert not MemoryLink.objects.filter(to_memory=a).exists()


# ---------------------------------------------------------------- veza sa F3


@pytest.mark.django_db
class TestBehaviourWritesMemory:
    def test_act_leaves_episode_with_run_source(self, mila):
        run = service.wake(mila, E.WakePriority.OPERATOR_TASK,
                           now=datetime(2026, 9, 21, 8, 10, tzinfo=UTC))
        if run.decision != E.WakeDecision.ACT:
            pytest.skip("prozor nije doneo ACT")
        m = MemoryItem.objects.get(persona=mila, source_event_id=f"run:{run.public_id}")
        assert m.memory_type == "episodic" and m.sources.first().run == run

    def test_world_store_only_is_remembered(self, mila):
        Persona.objects.filter(pk=mila.pk).update(status=E.PersonaStatus.ACTIVE)
        ev, routes = world.ingest(event_type="industry.news", topics=["gardening"], geo=["RS"],
                                  source="t", dedupe_key="so-1", now=NOW)
        assert routes[0].outcome == "store_only"
        assert MemoryItem.objects.filter(persona=mila,
                                         source_event_id=f"world:{ev.public_id}").exists()


# ---------------------------------------------------------------- API


@requires_db
@pytest.mark.django_db
class TestMemoryApi:
    def _client(self, name, role):
        from django.contrib.auth.models import Group, User
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        u = User.objects.create_user(username=name)
        u.groups.add(Group.objects.get_or_create(name=role.value)[0])
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}")
        return c

    def _h(self, actor, key=None):
        h = {"HTTP_X_REQUEST_ID": f"req-{key or 'q'}-xyz", "HTTP_X_ACTOR_ID": actor,
             "HTTP_TRACEPARENT": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
        if key:
            h["HTTP_IDEMPOTENCY_KEY"] = key
        return h

    def test_create_query_supersede_flow(self, mila):
        c = self._client("pm", E.Role.PERSONA_MANAGER)
        r = c.post("/api/v1/personas/P-00001/memories", {
            "memory_type": "semantic", "content": "Objavljuje 4x nedeljno",
            "assertion": {"subject": "P-00001", "predicate": "cadence", "value": 4},
        }, format="json", **self._h("user:pm", "mem-key-001"))
        assert r.status_code == 201, r.content
        mid = r.json()["data"]["memory"]["memory_id"]
        q = c.post("/api/v1/personas/P-00001/memories/query",
                   {"query": "koliko često objavljuje", "top_k": 5}, format="json",
                   **self._h("user:pm"))
        assert q.status_code == 200 and "why" in q.json()["data"][0]
        s = c.post(f"/api/v1/memories/{mid}/supersede",
                   {"content": "2", "reason": "nova odobrena konfiguracija"}, format="json",
                   **self._h("user:pm", "sup-key-001"))
        assert s.status_code == 201, s.content
        assert MemoryItem.objects.get(id=mid).status == "SUPERSEDED"

    def test_secret_is_rejected(self, mila):
        c = self._client("pm2", E.Role.PERSONA_MANAGER)
        r = c.post("/api/v1/personas/P-00001/memories",
                   {"memory_type": "semantic", "content": "api_key=abcd1234efgh5678"},
                   format="json", **self._h("user:pm2", "mem-key-sec1"))
        assert r.status_code == 400
        assert r.json()["error"]["details"]["code"] == "SECRET_MATERIAL"

    def test_viewer_cannot_read_memory(self, mila):
        c = self._client("v", E.Role.VIEWER)
        r = c.post("/api/v1/personas/P-00001/memories/query", {"query": "x"}, format="json",
                   **self._h("user:v"))
        assert r.status_code == 403

    def test_context_build(self, mila):
        run = _run(mila)
        c = self._client("op", E.Role.OPERATOR)
        r = c.post("/api/v1/context/build", {
            "persona_id": "P-00001", "run_id": run.public_id, "profile": "daily_planner",
            "query": "plan dana", "max_tokens": 1200,
        }, format="json", **self._h("user:op", "ctx-key-001"))
        assert r.status_code == 201, r.content
        body = r.json()["data"]
        assert body["token_count"] <= 1200 and body["pack_hash"]
        assert AgentRun.objects.get(public_id=run.public_id).context_packs.count() == 1
