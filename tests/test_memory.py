"""F4 — Memory & Knowledge. ADR-0006.

Prati Memory v0.1 §20 i Definition of Done §21.1: idempotentnost, supersesija,
protivrečnosti bez izmišljenog pobednika, izolacija persona, osetljivost po
svrsi, bleđenje, konsolidacija sa lozom, tvrdi plafon tokena, brisanje sa
propagacijom i zlatni skup kao regresiona kapija.

TestVestineInContext (ADR-0096) proverava da veštine iz baze znanja stižu u
paket svakog agenta, ne samo pisca koda.
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
    KnowledgeFact,
    KnowledgeSource,
    MemoryContextPack,
    MemoryContradiction,
    MemoryEmbedding,
    MemoryItem,
    MemoryLink,
)
from apps.memory.vestine import PREDIKAT
from apps.memory.writer import MemoryInput, MemoryRejected, write
from apps.observability.models import EventOutbox
from apps.orchestration.models import AgentRun
from apps.personas.models import Assignment, Department, Persona, Position
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


def _rasporedi(persona, sektor: str, now=None):
    """Stavlja personu u sektor (ADR-0017), da bi izbor veština po sektoru
    (ADR-0101) imao šta da pročita. Sektor se pravi ovde, bez `seed_org`,
    da test zavisi od što manje tuđeg stanja."""
    dep = Department.objects.create(code=sektor, name=f"Sektor {sektor}")
    poz = Position.objects.create(
        department=dep, code=f"{sektor}-TEST", title=f"Radno mesto {sektor}",
        duties=[], needs=[],
    )
    return Assignment.objects.create(
        persona=persona, position=poz, started_at=now or NOW, is_primary=True,
    )


def _vestina(*, subject="veština test", license_box=E.LicenseBox.SLOBODNA,
             license_note="MIT", is_active=True, koraci=None, napomene="",
             confidence=0.8, sector=""):
    """Kreira `KnowledgeSource`/`KnowledgeFact` direktno, bez prolaska kroz
    `uvezi()`, da testovi ADR-0096 mogu nezavisno da kontrolišu
    `is_active`/`license_box` izvora."""
    izvor = KnowledgeSource.objects.create(
        persona=None, source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
        title=f"Izvor za {subject}", trust_score=1.0, is_active=is_active,
        license_box=E.LicenseBox(license_box).value, license_note=license_note,
        sector=sector,
    )
    return KnowledgeFact.objects.create(
        source=izvor, persona=None, subject=subject, predicate=PREDIKAT,
        provenance=E.Provenance.USER_PROVIDED.value, confidence=confidence,
        object_json={"koraci": koraci or ["korak jedan"], "napomene": napomene},
    )


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
        # Flaky ispravka: seed memorije su PINNED sa visokim salience-om, pa mogu
        # da izjednače ukupan skor sa upisanom — [0] (vrh) je tada nekad seed sa
        # semantic=0, a tiebreak po slučajnom UUID-u prevrće rezultat. Proveravamo
        # breakdown TAČNO upisane memorije (to i jeste namera testa), uz now=NOW
        # kao i svi ostali upisi u ovom fajlu.
        m = write(mila, _m("Kupci u građevini pitaju za rok isporuke"), now=NOW).memory
        scored = retrieval.retrieve(mila, "rok isporuke građevina",
                                    E.RetrievalProfile.RESEARCH, now=NOW)
        nasa = next(s for s in scored if s.memory.pk == m.pk)
        assert set(retrieval.WEIGHTS) <= set(nasa.breakdown)
        assert nasa.breakdown["task_relevance"] > 0 and nasa.breakdown["semantic"] > 0

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


# ---------------------------------------------------------------- veštine (ADR-0096)


@pytest.mark.django_db
class TestVestineInContext:
    """Veštine iz baze znanja stižu u paket svakog agenta, ne samo pisca koda."""

    def test_slobodna_i_aktivna_ulazi_u_tekst_i_u_vestina_ids(self, mila):
        fact = _vestina(subject="veština vidljiva u paketu")
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="bilo šta", now=NOW)
        assert "veština vidljiva u paketu" in pack.text
        assert str(fact.id) in pack.record.vestina_ids

    def test_nedozvoljena_licenca_ne_ulazi(self, mila):
        for box in (E.LicenseBox.ZARAZNA, E.LicenseBox.ZABRANJENA, E.LicenseBox.NEPOZNATA):
            fact = _vestina(subject=f"veština kutija {box.value}", license_box=box)
            pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                                 query="bilo šta", now=NOW)
            assert fact.subject not in pack.text
            assert str(fact.id) not in pack.record.vestina_ids

    def test_neaktivan_izvor_ne_ulazi(self, mila):
        fact = _vestina(subject="veština neaktivnog izvora", is_active=False)
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="bilo šta", now=NOW)
        assert fact.subject not in pack.text
        assert str(fact.id) not in pack.record.vestina_ids

    def test_vestine_ne_oduzimaju_prostor_memoriji(self, mila):
        """Isti broj memorija u paketu sa veštinom i bez nje, nad ISTOM personom.

        Dve persone u poređenju bi unele i razliku koja sa ovim pitanjem nema
        veze (npr. odsustvo `BehaviourState`). Ovde se, između dva merenja,
        menja SAMO prisustvo veštine: prvo se paket gradi dok je izvor
        aktivan, zatim se izvor deaktivira i paket se gradi ponovo.
        """
        content = "o logistici i transportu robe " + "reč " * 40
        for i in range(40):
            write(mila, _m(f"Memorijska {i} {content}", source_event_id=f"vest-{i}"))
        fact = _vestina(subject="veština za poređenje")
        sa_vestinom = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                                    query="logistika transport", now=NOW)
        KnowledgeSource.objects.filter(pk=fact.source_id).update(is_active=False)
        bez_vestine = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                                    query="logistika transport", now=NOW)
        assert len(sa_vestinom.record.memory_ids) == len(bez_vestine.record.memory_ids)

    def test_dosije_firme_je_u_paketu(self, mila):
        """ADR-0107 — agent zna gde radi, pre nego što bilo šta uradi."""
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="bilo šta", now=NOW)
        assert "Web Korporacija" in pack.text
        assert "Trenutno isključivo za vlasnika" in pack.text
        assert "kocku i klađenje" in pack.text        # granice idu uz posao

    def test_bez_dosijea_paket_i_dalje_radi(self, mila, monkeypatch):
        """Fajla može da nema (tuđa grana, stari primerak) — to nije pad."""
        monkeypatch.setattr(context, "_dosije_firme", lambda: "")
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="bilo šta", now=NOW)
        assert "Web Korporacija" not in pack.text
        assert pack.record.token_count > 0

    def test_vestina_iz_sektora_persone_ide_prva(self, mila):
        """ADR-0101 — sektor bije azbuku. Tuđa veština je azbučno prva, a
        ipak ide iza naše."""
        _rasporedi(mila, "MARKETING")
        tudja = _vestina(subject="a tuđa veština", sector="RAZVOJ")
        nasa = _vestina(subject="z naša veština", sector="MARKETING")
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="bilo šta", now=NOW)
        assert pack.record.vestina_ids[0] == str(nasa.id)
        assert pack.record.vestina_ids.index(str(tudja.id)) > 0

    def test_izvor_bez_sektora_ide_ispred_tudjeg_sektora(self, mila):
        """ADR-0101 — prazan sektor znači „za sve", pa dolazi pre tuđeg."""
        _rasporedi(mila, "MARKETING")
        tudja = _vestina(subject="a tuđa veština", sector="RAZVOJ")
        za_sve = _vestina(subject="z veština za sve", sector="")
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="bilo šta", now=NOW)
        assert pack.record.vestina_ids.index(str(za_sve.id)) < \
            pack.record.vestina_ids.index(str(tudja.id))

    def test_unutar_istog_sektora_odlucuje_poklapanje_sa_zadatkom(self, mila):
        """ADR-0101 — kad je sektor isti, bira tekst zadatka, pa tek onda azbuka."""
        _rasporedi(mila, "MARKETING")
        prva_azbucno = _vestina(subject="a nevezana veština", sector="MARKETING")
        pogodjena = _vestina(subject="z pisanje ponude", sector="MARKETING")
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="treba mi pisanje ponude za kupca", now=NOW)
        assert pack.record.vestina_ids[0] == str(pogodjena.id)
        assert str(prva_azbucno.id) in pack.record.vestina_ids

    def test_bez_rasporeda_sektor_ne_odlucuje_nista(self, mila):
        """ADR-0101 — persona bez rasporeda nema sektor; tada vredi stari
        redosled, azbučni, i ništa se ne lomi."""
        prva = _vestina(subject="a veština", sector="RAZVOJ")
        druga = _vestina(subject="b veština", sector="MARKETING")
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="", now=NOW)
        assert pack.record.vestina_ids == [str(prva.id), str(druga.id)]

    def test_prekoracenje_plafona_vestina_postavlja_truncated(self, mila):
        """ADR-0112 — i indeksne linije imaju plafon; dovoljno veština ga probije."""
        for i in range(40):
            _vestina(subject=f"veština velika {i:02d}")
        pack = context.build(mila, _run(mila), E.RetrievalProfile.REFLECTION,
                             query="bilo šta", now=NOW)
        assert pack.record.truncated is True
        assert 0 < len(pack.record.vestina_ids) < 40

    def test_vrh_u_celini_ostalo_indeks(self, mila):
        """ADR-0112 — vrh rangiranja nosi korake, ostatak samo ime + opis."""
        for i in range(8):
            _vestina(subject=f"veština {i:02d}", koraci=[f"korak-za-{i:02d}"])
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="", now=NOW)
        assert "U celini (sa koracima):" in pack.text
        assert "Još veština koje imaš" in pack.text
        assert "korak-za-00" in pack.text          # puna veština nosi korake
        assert "veština 04" in pack.text            # indeksna nosi ime
        assert "korak-za-04" not in pack.text        # ali ne i korake

    def test_indeks_nosi_izvor(self, mila):
        """ADR-0084 — i indeksna veština mora da nosi poreklo."""
        for i in range(8):
            _vestina(subject=f"veština {i:02d}", koraci=[f"korak-za-{i:02d}"])
        pack = context.build(mila, _run(mila), E.RetrievalProfile.RESEARCH,
                             query="", now=NOW)
        # Red za indeksnu veštinu „04" i dalje ima oznaku izvora.
        red = next(r for r in pack.text.splitlines() if "veština 04" in r)
        assert "izvor" in red

    def test_mnogo_vise_vestina_stane_nego_pre(self, mila):
        """ADR-0112 — poenta promene: pre je stajalo ~4, sada deset puta više."""
        for i in range(30):
            _vestina(subject=f"veština {i:02d}",
                     koraci=[f"korak-{i:02d}-a", f"korak-{i:02d}-b"])
        pack = context.build(mila, _run(mila), E.RetrievalProfile.CONTENT_CREATION,
                             query="", now=NOW)
        assert len(pack.record.vestina_ids) >= 15


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
