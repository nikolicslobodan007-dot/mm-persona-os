"""Testovi izvlačenja tvrdnji iz Libri blokova (ADR-0031 sloj 4a).

Ekstraktor je determinističan (bez LLM), pa se i KVALITET (preciznost/odziv na
zlatnom skupu) meri ovde u gejtu, ne samo na produkciji. Ostalo pokriva ugovor:
definicione rečenice se hvataju, nedefinicione i naslovi se preskaču, upis pravi
KnowledgeFact sa poreklom do bloka i radi delete+recreate.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from api.context import bind
from apps.libri import tvrdnje
from apps.libri.management.commands.libri_tvrdnje_eval import run_eval
from apps.libri.models import Block, LibriDocument
from apps.memory.models import KnowledgeFact, KnowledgeSource
from common import enums as E
from tests.conftest import requires_db


def _blok(text, *, i=1, block_type="paragraph"):
    return SimpleNamespace(block_type=block_type, text=text,
                           block_id=f"blk_{i:06d}", source_page=1)


def _dok_sa_izvorom(blokovi, *, document_id="doc_tvrdnje", sa_izvorom=True):
    izvor = None
    if sa_izvorom:
        izvor = KnowledgeSource.objects.create(
            persona=None, title="Tvrdnje izvor",
            source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
            trust_score=Decimal("1.000"))
    dok = LibriDocument.objects.create(
        source=izvor, document_id=document_id, version_id="v1", title="T",
        language="sr-Latn", script="latin", pages=1, schema_version="lkp-0.1",
        ingested_at=timezone.now())
    Block.objects.bulk_create([
        Block(document=dok, block_id=f"blk_{i:06d}", block_type=bt, text=t,
              language="sr-Latn", order=i + 1, extraction_confidence=Decimal("0.9"))
        for i, (bt, t) in enumerate(blokovi)
    ])
    return dok, izvor


def test_izvuci_hvata_definicione():
    kand = tvrdnje.izvuci([
        _blok("Furnir je vrlo tanak list drveta koji se lepi na osnovu.", i=1),
        _blok("Rende je ručni alat koji skida tanak sloj drveta.", i=2),
    ])
    assert [k["subject"] for k in kand] == ["Furnir", "Rende"]
    assert kand[0]["relacija"] == "je"
    assert kand[0]["block_id"] == "blk_000001"
    assert "tanak list drveta" in kand[0]["vrednost"]


def test_izvuci_preskace_nedefinicione_i_naslove():
    kand = tvrdnje.izvuci([
        _blok("Brušenje se radi u nekoliko prolaza do glatke površine.", i=1),
        _blok("Majstor bira drvo prema nameni.", i=2),
        _blok("FURNIR JE SKUP", i=3, block_type="heading"),
    ])
    assert kand == []


@requires_db
@pytest.mark.django_db
def test_upisi_pravi_knowledge_fact(db):
    dok, izvor = _dok_sa_izvorom([
        ("paragraph", "Tipl je drveni čep koji spaja dve daske."),
        ("paragraph", "Brušenje se radi u nekoliko prolaza."),  # nije tvrdnja
    ])
    with bind(actor_id="user:qa"):
        rez = tvrdnje.upisi(dok)
    assert rez == {"upisano": 1, "obrisano": 0}
    f = KnowledgeFact.objects.get(source=izvor, predicate=tvrdnje.PREDIKAT)
    assert f.subject == "Tipl"
    assert f.provenance == E.Provenance.OBSERVED.value
    assert f.object_json["block_id"] == "blk_000000"
    assert "drveni čep" in f.object_json["vrednost"]


@requires_db
@pytest.mark.django_db
def test_upisi_delete_recreate_idempotentno(db):
    dok, izvor = _dok_sa_izvorom([
        ("paragraph", "Lak je zaštitni premaz za drvo.")])
    with bind(actor_id="user:qa"):
        prvi = tvrdnje.upisi(dok)
        drugi = tvrdnje.upisi(dok)
    assert prvi == {"upisano": 1, "obrisano": 0}
    assert drugi == {"upisano": 1, "obrisano": 1}  # staro obrisano, novo upisano
    assert KnowledgeFact.objects.filter(
        source=izvor, predicate=tvrdnje.PREDIKAT).count() == 1


@requires_db
@pytest.mark.django_db
def test_upisi_bez_izvora_pada(db):
    dok, _ = _dok_sa_izvorom(
        [("paragraph", "Tipl je drveni čep.")], sa_izvorom=False)
    with pytest.raises(ValueError, match="nema izvor"):
        tvrdnje.upisi(dok)


def test_osnova_meri_preciznost_i_odziv():
    r = run_eval()
    # Determinističkoj osnovi na zlatnom skupu — bez lažnih, svi očekivani uhvaćeni.
    assert r["preciznost"] == 1.0, r["lazno"]
    assert r["odziv"] == 1.0, r["promaseno"]
