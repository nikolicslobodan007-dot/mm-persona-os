"""Testovi računice pouzdanosti po pet osa (ADR-0031 sloj 4b §3.3).

Računica je deterministička (bez LLM), pa se vrednosti mere ovde u gejtu na
scenarijima. Semantika: potkrepa i nezavisnost rastu sa saglasnim izvorima,
stabilnost pada sa protivrečnim — i to BEZ biranja pobednika (obe tvrdnje ostaju,
ADR-0006 §3). Upis pravi jednu OcenaTvrdnje po tvrdnji, delete+recreate po izvoru.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from api.context import bind
from apps.libri import pouzdanost, tvrdnje
from apps.libri.management.commands.libri_pouzdanost_eval import run_eval
from apps.libri.models import Block, LibriDocument, OcenaTvrdnje
from apps.memory.models import KnowledgeFact, KnowledgeSource
from common import enums as E
from tests.conftest import requires_db


def _ns(subject, vrednost, trust, kind, sid):
    return pouzdanost.scenario_namespaces([{
        "subject": subject, "predicate": "libri.tvrdnja", "vrednost": vrednost,
        "trust": trust, "source_kind": kind, "source_id": sid}])[0]


def _dok_sa_izvorom(recenice, *, document_id="doc_ocena", sa_izvorom=True):
    izvor = None
    if sa_izvorom:
        izvor = KnowledgeSource.objects.create(
            persona=None, title="Ocena izvor",
            source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
            trust_score=Decimal("0.800"))
    dok = LibriDocument.objects.create(
        source=izvor, document_id=document_id, version_id="v1", title="T",
        language="sr-Latn", script="latin", pages=1, schema_version="lkp-0.1",
        ingested_at=timezone.now())
    Block.objects.bulk_create([
        Block(document=dok, block_id=f"blk_{i:06d}", block_type="paragraph", text=t,
              language="sr-Latn", order=i + 1, extraction_confidence=Decimal("0.9"))
        for i, t in enumerate(recenice)
    ])
    return dok, izvor


def test_jedan_izvor_osnova():
    tv = _ns("Furnir", "tanak list drveta", 0.8, "first_party_user_input", "s1")
    o = pouzdanost.oceni(tv, [tv])
    assert o["pouzdanost"] == 0.8
    assert o["blizina"] == 0.9
    assert o["potkrepljenost"] == 0.2
    assert o["nezavisnost"] == 0.5
    assert o["stabilnost"] == 1.0
    assert o["ukupno"] == 0.68


def test_potkrepa_i_nezavisnost_rastu():
    a = _ns("Furnir", "tanak list drveta", 0.8, "first_party_user_input", "s1")
    b = _ns("Furnir", "tanak list drveta", 0.7, "public_web_source", "s2")
    sam = pouzdanost.oceni(a, [a])
    dva = pouzdanost.oceni(a, [a, b])
    assert dva["potkrepljenost"] > sam["potkrepljenost"]
    assert dva["nezavisnost"] > sam["nezavisnost"]
    assert dva["ukupno"] > sam["ukupno"]


def test_protivrecnost_snizava_stabilnost_bez_pobednika():
    a = _ns("Furnir", "tanak list drveta", 0.8, "first_party_user_input", "s1")
    c = _ns("Furnir", "debela ploča", 0.6, "public_web_source", "s2")
    sam = pouzdanost.oceni(a, [a])
    sukob = pouzdanost.oceni(a, [a, c])
    assert sukob["stabilnost"] < sam["stabilnost"]
    # Bez pobednika: i protivrečna tvrdnja dobija ocenu (ostaje, ne briše se).
    druga = pouzdanost.oceni(c, [a, c])
    assert 0 <= druga["stabilnost"] < 1


def test_osnova_scenariji_tacni():
    r = run_eval()
    assert r["ispravno"], r["greske"]


@requires_db
@pytest.mark.django_db
def test_upisi_ocenjuje_tvrdnje(db):
    dok, izvor = _dok_sa_izvorom([
        "Furnir je tanak list drveta koji se lepi preko osnove.",
        "Rende je ručni alat koji skida tanak sloj drveta.",
    ])
    with bind(actor_id="user:qa"):
        tvrdnje.upisi(dok)
        rez = pouzdanost.upisi(dok)
    broj_tvrdnji = KnowledgeFact.objects.filter(
        source=izvor, predicate=tvrdnje.PREDIKAT).count()
    assert broj_tvrdnji >= 2
    assert rez == {"ocenjeno": broj_tvrdnji, "obrisano": 0}
    assert OcenaTvrdnje.objects.filter(fact__source=izvor).count() == broj_tvrdnji
    for o in OcenaTvrdnje.objects.filter(fact__source=izvor):
        assert Decimal("0") < o.ukupno <= Decimal("1")


@requires_db
@pytest.mark.django_db
def test_upisi_delete_recreate_idempotentno(db):
    dok, izvor = _dok_sa_izvorom(["Furnir je tanak list drveta."])
    with bind(actor_id="user:qa"):
        tvrdnje.upisi(dok)
        prvi = pouzdanost.upisi(dok)
        drugi = pouzdanost.upisi(dok)
    assert prvi["obrisano"] == 0
    assert drugi["obrisano"] == prvi["ocenjeno"]
    assert OcenaTvrdnje.objects.filter(fact__source=izvor).count() == prvi["ocenjeno"]


@requires_db
@pytest.mark.django_db
def test_upisi_bez_izvora_pada(db):
    dok, _ = _dok_sa_izvorom(["Furnir je tanak list drveta."], sa_izvorom=False)
    with pytest.raises(ValueError, match="nema izvor"):
        pouzdanost.upisi(dok)
