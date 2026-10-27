"""Testovi dosija dokumenta (ADR-0031 sloj 4c, §3.4).

Dosije je IZVEDEN dokument (ne čuva se u bazi). `_markdown` je čista funkcija pa se
struktura (svih 12 sekcija) meri bez baze; `sastavi` se proverava na stvarnim
podacima (tvrdnje + entiteti + odnosi + pouzdanost) i na praznom dokumentu
(prazne sekcije daju „—", ništa se ne izmišlja).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from api.context import bind
from apps.libri import dosije, entiteti, pouzdanost, tvrdnje
from apps.libri.models import Block, LibriDocument
from apps.memory.models import KnowledgeSource
from common import enums as E
from tests.conftest import requires_db


def _prazno():
    return {
        "naslov": "Prazno", "document_id": "doc_x", "poreklo": "(bez izvora)",
        "blokova": 0, "tvrdnje": [], "akteri": [], "dogadjaji": [], "dokazi": [],
        "odnosi": [], "kontradikcije": [], "hronologija": [],
        "pouzdanost": {"pouzdanost": 0.0, "nezavisnost": 0.0, "blizina": 0.0,
                       "potkrepljenost": 0.0, "stabilnost": 0.0, "ukupno": 0.0, "broj": 0},
    }


def test_markdown_ima_svih_dvanaest_sekcija():
    md = dosije._markdown(_prazno())
    for i in range(1, 13):
        assert f"## {i}. " in md, f"fali sekcija {i}"
    assert "## 11. Hronologija" in md
    assert "## 12. Upozorenje" in md
    # Prazne sekcije ne izmišljaju sadržaj.
    assert "—" in md


def _dok(recenice, *, document_id="doc_dosije"):
    izvor = KnowledgeSource.objects.create(
        persona=None, title="Dosije izvor",
        source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
        trust_score=Decimal("0.800"))
    dok = LibriDocument.objects.create(
        source=izvor, document_id=document_id, version_id="v1",
        title="Proba dokument", language="sr-Latn", script="latin", pages=1,
        schema_version="lkp-0.1", ingested_at=timezone.now())
    Block.objects.bulk_create([
        Block(document=dok, block_id=f"blk_{i:06d}", block_type="paragraph", text=t,
              language="sr-Latn", order=i + 1, extraction_confidence=Decimal("0.9"))
        for i, t in enumerate(recenice)
    ])
    return dok, izvor


@requires_db
@pytest.mark.django_db
def test_sastavi_na_stvarnim_podacima(db):
    dok, _izvor = _dok([
        "Furnir je tanak list drveta koji se lepi preko osnove.",
        "Milan Jovanović radi u kompaniji Vinogradi.",
    ])
    with bind(actor_id="user:qa"):
        tvrdnje.upisi(dok)
        entiteti.upisi(dok)
        pouzdanost.upisi(dok)
    md = dosije.sastavi(dok)
    for i in range(1, 13):
        assert f"## {i}. " in md, f"fali sekcija {i}"
    assert "Furnir" in md                       # tvrdnja
    assert "Milan Jovanović" in md              # akter
    assert "Vinogradi" in md                    # akter
    assert "radi_u" in md                       # mreža odnosa
    assert "## 6. Pouzdanost izvora" in md
    assert "ukupno" in md


@requires_db
@pytest.mark.django_db
def test_sastavi_prazan_dokument_ima_crtice(db):
    dok, _ = _dok(["Brušenje se radi u nekoliko prolaza do glatke površine."])
    md = dosije.sastavi(dok)
    for i in range(1, 13):
        assert f"## {i}. " in md, f"fali sekcija {i}"
    assert "—" in md
