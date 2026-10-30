"""Testovi izvlačenja entiteta i odnosa iz Libri blokova (ADR-0031 sloj 4b).

Ekstraktor je determinističan (bez LLM), pa se KVALITET (preciznost/odziv na
zlatnom skupu) meri ovde u gejtu, ne samo na produkciji. Ostalo pokriva ugovor:
entitet se pravi samo uz pokaznu reč, odnos samo između dva prepoznata entiteta
(zato nema lažnih veza), događaj nosi dvostruko vreme, a upis pravi Entitet/Odnos
sa poreklom do bloka i radi delete+recreate po izvoru.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from api.context import bind
from apps.libri import entiteti
from apps.libri.management.commands.libri_entiteti_eval import run_eval
from apps.libri.models import (
    ENTITY_KINDS,
    RELATION_TYPES,
    Block,
    Entitet,
    LibriDocument,
    Odnos,
)
from apps.memory.models import KnowledgeSource
from common import enums as E
from tests.conftest import requires_db


def _blok(text, *, i=1):
    return SimpleNamespace(block_type="paragraph", text=text,
                           block_id=f"blk_{i:06d}", source_page=1)


def _dok_sa_izvorom(recenice, *, document_id="doc_graf", sa_izvorom=True):
    izvor = None
    if sa_izvorom:
        izvor = KnowledgeSource.objects.create(
            persona=None, title="Graf izvor",
            source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
            trust_score=Decimal("1.000"))
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


def test_izvuci_entitete_hvata_vrstu():
    ent = entiteti.izvuci_entitete([
        _blok("Milan Jovanović radi u kompaniji Vinogradi.", i=1),
    ])
    parovi = {(e["name"], e["kind"]) for e in ent}
    assert parovi == {("Milan Jovanović", "osoba"), ("Vinogradi", "organizacija")}
    assert ent[0]["block_id"] == "blk_000001"


def test_izvuci_preskace_bez_pokazne():
    ent = entiteti.izvuci_entitete([
        _blok("Brušenje se radi u nekoliko prolaza do glatke površine.", i=1),
        _blok("Furnir je vrlo tanak list drveta.", i=2),
    ])
    assert ent == []


def test_izvuci_odnose_samo_izmedju_entiteta():
    blok = _blok("Brušenje se radi u nekoliko prolaza.", i=1)
    ent = entiteti.izvuci_entitete([blok])
    assert entiteti.izvuci_odnose([blok], ent) == []
    blok2 = _blok("Ana Petrović je direktorka preduzeća Drvo Promet.", i=2)
    ent2 = entiteti.izvuci_entitete([blok2])
    odn = entiteti.izvuci_odnose([blok2], ent2)
    assert [(o["subject"], o["relation_type"], o["object"]) for o in odn] == \
        [("Ana Petrović", "vodi", "Drvo Promet")]


def test_dvostruko_vreme_na_dogadjaju():
    ent = entiteti.izvuci_entitete([_blok("Sajam Drvo održan je 12.03.2026.", i=1)])
    assert len(ent) == 1
    assert ent[0]["kind"] == "dogadjaj"
    assert ent[0]["desilo_se"] == "2026-03-12"
    assert ent[0]["objavljeno"] is None


def test_vokabular_se_slaze_sa_modelima():
    assert set(entiteti.VRSTE) == set(ENTITY_KINDS)
    assert set(entiteti.TIPOVI_ODNOSA) == set(RELATION_TYPES)


@requires_db
@pytest.mark.django_db
def test_upisi_pravi_entitet_i_odnos(db):
    dok, izvor = _dok_sa_izvorom([
        "Milan Jovanović radi u kompaniji Vinogradi.",
        "Brušenje se radi u nekoliko prolaza.",  # bez entiteta
    ])
    with bind(actor_id="user:qa"):
        rez = entiteti.upisi(dok)
    assert rez == {"entiteta": 2, "odnosa": 1, "obrisano": 0}
    org = Entitet.objects.get(source=izvor, kind="organizacija")
    assert org.name == "Vinogradi"
    assert org.object_json["block_id"] == "blk_000000"
    odnos = Odnos.objects.get(source=izvor)
    assert odnos.relation_type == "radi_u"
    assert odnos.subject.name == "Milan Jovanović"
    assert odnos.object.name == "Vinogradi"


@requires_db
@pytest.mark.django_db
def test_upisi_delete_recreate_idempotentno(db):
    dok, izvor = _dok_sa_izvorom(["Marko Ilić je osnovao kompaniju Tipl Sistem."])
    with bind(actor_id="user:qa"):
        prvi = entiteti.upisi(dok)
        drugi = entiteti.upisi(dok)
    assert prvi == {"entiteta": 2, "odnosa": 1, "obrisano": 0}
    assert drugi == {"entiteta": 2, "odnosa": 1, "obrisano": 3}  # 2 ent + 1 odnos obrisano
    assert Entitet.objects.filter(source=izvor).count() == 2
    assert Odnos.objects.filter(source=izvor).count() == 1


@requires_db
@pytest.mark.django_db
def test_upisi_bez_izvora_pada(db):
    dok, _ = _dok_sa_izvorom(
        ["Milan Jovanović radi u kompaniji Vinogradi."], sa_izvorom=False)
    with pytest.raises(ValueError, match="nema izvor"):
        entiteti.upisi(dok)


def test_osnova_meri_preciznost_i_odziv():
    r = run_eval()
    assert r["preciznost_entiteti"] == 1.0, r["lazno"]
    assert r["odziv_entiteti"] == 1.0, r["promaseno"]
    assert r["preciznost_odnosa"] == 1.0, r["lazno"]
    assert r["odziv_odnosa"] == 1.0, r["promaseno"]


def test_cirilica_entiteti_i_odnos():
    """Ćirilica: entiteti (osoba/organizacija) i odnos radi_u kao kod latinice."""
    blok = _blok("Милан Јовановић ради у компанији Виногради.", i=1)
    ent = entiteti.izvuci_entitete([blok])
    assert {(e["name"], e["kind"]) for e in ent} == {
        ("Милан Јовановић", "osoba"), ("Виногради", "organizacija")}
    odn = entiteti.izvuci_odnose([blok], ent)
    assert [(o["subject"], o["relation_type"], o["object"]) for o in odn] == \
        [("Милан Јовановић", "radi_u", "Виногради")]


def test_cirilica_dogadjaj_dvostruko_vreme():
    ent = entiteti.izvuci_entitete([_blok("Сајам Дрво одржан је 12.03.2026.", i=1)])
    assert len(ent) == 1
    assert ent[0]["kind"] == "dogadjaj"
    assert ent[0]["desilo_se"] == "2026-03-12"
