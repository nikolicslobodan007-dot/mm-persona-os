"""Testovi semantičke pretrage Libri blokova (ADR-0031 sloj 3).

Pravi model NE pozivamo — fastembed/ONNX nije u gejt-slici (isto kao
`test_vestine_semantika`). `embeddings.embed_semanticki` se lažira
determinističkim vektorom pa se meri UGOVOR (embedovanje, `text_hash` preskok,
kosinusni poredak, filter pouzdanosti/dozvole, fallback bez modela), a ne sam
model. Stvarno merenje kvaliteta je `libri_eval` na produkciji.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.utils import timezone

from apps.libri import vektori
from apps.libri.models import Block, BlockEmbedding, LibriDocument
from apps.memory import embeddings
from tests.conftest import requires_db

DIM = settings.VESTINA_EMBEDDING_DIM
#: reč-marker → indeks koji lažni model „upali"; isti marker u upitu i u bloku
#: daju isti vektor, pa im je kosinusna razdaljina 0.
MARKERI = {"alfa": 0, "beta": 1, "gama": 2}


def _laz_vektor(text, *, model=None):
    v = [0.0] * DIM
    low = text.lower()
    pogodak = False
    for marker, i in MARKERI.items():
        if marker in low:
            v[i] = 1.0
            pogodak = True
    if not pogodak:
        v[DIM - 1] = 1.0
    return v


def _dok(blokovi, *, document_id="doc_test3"):
    """blokovi: list[(block_id, text, confidence, perm_ai_read)] → (dok, [Block])."""
    dok = LibriDocument.objects.create(
        document_id=document_id, version_id="v1", title="Test sloj 3",
        language="sr-Latn", script="latin", pages=1, schema_version="lkp-0.1",
        ingested_at=timezone.now(),
    )
    objs = Block.objects.bulk_create([
        Block(document=dok, block_id=bid, block_type="paragraph", text=t,
              language="sr-Latn", order=i + 1, extraction_confidence=conf,
              perm_ai_read=air)
        for i, (bid, t, conf, air) in enumerate(blokovi)
    ])
    return dok, objs


@requires_db
@pytest.mark.django_db
def test_embeduj_pravi_vektore(db, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    _, blokovi = _dok([("blk_000001", "zadatak alfa", 0.9, True),
                       ("blk_000002", "zadatak beta", 0.9, True)])
    rez = vektori.embeduj(blokovi)
    assert rez == {"upisano": 2, "preskoceno": 0}
    mk = embeddings.vestina_model_key()
    assert BlockEmbedding.objects.count() == 2
    assert all(e.model_key == mk and e.dimensions == DIM
               for e in BlockEmbedding.objects.all())


@requires_db
@pytest.mark.django_db
def test_embeduj_bez_modela_ne_pada(db, monkeypatch):
    def pukni(text, *, model=None):
        raise RuntimeError("model nedostupan (offline)")

    monkeypatch.setattr(embeddings, "embed_semanticki", pukni)
    _, blokovi = _dok([("blk_000001", "zadatak alfa", 0.9, True)])
    rez = vektori.embeduj(blokovi)
    assert rez == {"upisano": 0, "preskoceno": 1}
    assert BlockEmbedding.objects.count() == 0
    assert Block.objects.count() == 1  # blok i dalje postoji


@requires_db
@pytest.mark.django_db
def test_text_hash_preskace_ponovno(db, monkeypatch):
    brojac = {"n": 0}

    def broji(text, *, model=None):
        brojac["n"] += 1
        return _laz_vektor(text)

    monkeypatch.setattr(embeddings, "embed_semanticki", broji)
    _, blokovi = _dok([("blk_000001", "zadatak alfa", 0.9, True)])
    vektori.embeduj(blokovi)
    assert brojac["n"] == 1
    drugi = vektori.embeduj(blokovi)
    assert brojac["n"] == 1  # isti tekst i model → nije ponovo računao
    assert drugi == {"upisano": 0, "preskoceno": 1}


@requires_db
@pytest.mark.django_db
def test_pretrazi_dize_pravi_blok(db, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    _, blokovi = _dok([("blk_000001", "tema alfa", 0.9, True),
                       ("blk_000002", "tema beta", 0.9, True),
                       ("blk_000003", "tema gama", 0.9, True)])
    vektori.embeduj(blokovi)
    rez = vektori.pretrazi("treba mi beta", top_k=3)
    assert rez is not None and rez[0][0].block_id == "blk_000002"
    assert {b.block_id for b, _ in rez} == {"blk_000001", "blk_000002", "blk_000003"}


@requires_db
@pytest.mark.django_db
def test_pretrazi_filter_pouzdanost_i_dozvola(db, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    _, blokovi = _dok([
        ("blk_dobar", "tema alfa", 0.9, True),     # prolazi
        ("blk_slab", "tema alfa", 0.3, True),      # ispod praga pouzdanosti
        ("blk_zabran", "tema alfa", 0.9, False),   # bez ai_read dozvole
    ])
    vektori.embeduj(blokovi)
    rez = vektori.pretrazi("tema alfa", top_k=10, min_confidence=0.6)
    assert rez is not None
    assert [b.block_id for b, _ in rez] == ["blk_dobar"]


@requires_db
@pytest.mark.django_db
def test_pretrazi_bez_modela_vraca_none(db, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    _, blokovi = _dok([("blk_000001", "tema alfa", 0.9, True)])
    vektori.embeduj(blokovi)

    def pukni(text, *, model=None):
        raise RuntimeError("offline")

    monkeypatch.setattr(embeddings, "embed_semanticki", pukni)
    assert vektori.pretrazi("tema alfa") is None


@requires_db
@pytest.mark.django_db
def test_pretrazi_ogranicava_na_dokument(db, monkeypatch):
    # Isti block_id u dva dokumenta (block_id nije jedinstven globalno) — bez
    # ograničenja bi se blokovi mešali; sa document_id vraća samo traženi dokument.
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    _, a = _dok([("blk_000001", "tema alfa", 0.9, True)], document_id="doc_a")
    _, b = _dok([("blk_000001", "tema alfa", 0.9, True)], document_id="doc_b")
    vektori.embeduj(a + b)
    rez = vektori.pretrazi("tema alfa", top_k=10, document_id="doc_a")
    assert rez is not None
    assert [bl.document.document_id for bl, _ in rez] == ["doc_a"]
