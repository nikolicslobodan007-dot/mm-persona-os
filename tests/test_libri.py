"""Libri sloj 1 — LKP blok (ADR-0031).

Meri temelj: šema legne i CHECK ograničenja zaista drže u PostgreSQL-u (CHECK koji
postoji u modelu a ne u bazi ne štiti ništa — isti princip kao test_models.py).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.libri.models import Block, LibriDocument
from tests.conftest import requires_db

pytestmark = [requires_db]


def _dok(**kw):
    kw.setdefault("document_id", "DOC-proba-1")
    kw.setdefault("title", "Proba")
    return LibriDocument.objects.create(**kw)


def _blok(dok, **kw):
    kw.setdefault("block_id", "b1")
    kw.setdefault("block_type", "paragraph")
    kw.setdefault("text", "Tekst bloka.")
    kw.setdefault("order", 0)
    kw.setdefault("extraction_confidence", Decimal("0.9"))
    return Block.objects.create(document=dok, **kw)


class TestLibriSema:
    def test_dokument_i_blok_se_prave(self, db):
        d = _dok()
        b = _blok(d)
        assert b.document == d
        assert d.blocks.count() == 1
        # podrazumevane LKP dozvole/kvalitet
        assert b.perm_ai_read and b.perm_quote and b.perm_export
        assert b.human_verified is False

    def test_jedinstven_blok_u_dokumentu(self, db):
        d = _dok()
        _blok(d, block_id="b1")
        with pytest.raises(IntegrityError), transaction.atomic():
            _blok(d, block_id="b1")

    def test_isti_block_id_u_drugom_dokumentu_prolazi(self, db):
        d1 = _dok(document_id="DOC-1")
        d2 = _dok(document_id="DOC-2")
        _blok(d1, block_id="b1")
        _blok(d2, block_id="b1")  # jedinstvenost je po dokumentu, ne globalno
        assert Block.objects.filter(block_id="b1").count() == 2

    def test_jedinstven_document_id(self, db):
        _dok(document_id="DOC-X")
        with pytest.raises(IntegrityError), transaction.atomic():
            _dok(document_id="DOC-X")

    def test_pouzdanost_van_opsega_pada(self, db):
        d = _dok()
        with pytest.raises(IntegrityError), transaction.atomic():
            _blok(d, extraction_confidence=Decimal("1.5"))

    def test_nepoznat_tip_bloka_pada(self, db):
        d = _dok()
        with pytest.raises(IntegrityError), transaction.atomic():
            _blok(d, block_type="table")

    def test_brisanje_dokumenta_brise_blokove(self, db):
        d = _dok()
        _blok(d)
        d.delete()
        assert Block.objects.count() == 0
