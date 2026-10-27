"""Testovi Libri pokretača (ADR-0123): Veritasove faze kao jedan tok.

Ceo tok (Čitač → Kartograf/Hroničar → Proveravač → Bibliotekar) nad dokumentom;
Čuvar odbija dokument bez izvora ili bez blokova pre početka; tok je idempotentan
(dupli run isti rezultat — svaki `upisi` je delete+recreate).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from api.context import bind
from apps.libri import steps
from apps.libri.models import Block, LibriDocument
from apps.memory.models import KnowledgeSource
from common import enums as E
from tests.conftest import requires_db


def _dok(recenice, *, document_id="doc_plan", sa_izvorom=True, sa_blokovima=True):
    izvor = None
    if sa_izvorom:
        izvor = KnowledgeSource.objects.create(
            persona=None, title="Plan izvor",
            source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
            trust_score=Decimal("0.800"))
    dok = LibriDocument.objects.create(
        source=izvor, document_id=document_id, version_id="v1", title="Proba",
        language="sr-Latn", script="latin", pages=1, schema_version="lkp-0.1",
        ingested_at=timezone.now())
    if sa_blokovima:
        Block.objects.bulk_create([
            Block(document=dok, block_id=f"blk_{i:06d}", block_type="paragraph", text=t,
                  language="sr-Latn", order=i + 1, extraction_confidence=Decimal("0.9"))
            for i, t in enumerate(recenice)
        ])
    return dok


@requires_db
@pytest.mark.django_db
def test_pokreni_ceo_tok(db):
    dok = _dok([
        "Furnir je tanak list drveta koji se lepi preko osnove.",
        "Milan Jovanović radi u kompaniji Vinogradi.",
    ])
    with bind(actor_id="user:qa"):
        rez = steps.pokreni(dok)
    assert [f["naziv"] for f in rez["faze"]] == [
        "Čitač", "Kartograf+Hroničar", "Proveravač", "Bibliotekar"]
    assert rez["faze"][0]["rezultat"]["tvrdnje"] >= 1   # Čitač našao definicionu tvrdnju
    md = rez["dosije"]
    for i in range(1, 13):                               # Bibliotekar: svih 12 sekcija
        assert f"## {i}. " in md


@requires_db
@pytest.mark.django_db
def test_cuvar_bez_izvora(db):
    dok = _dok(["Nebitno."], document_id="doc_bez_izvora", sa_izvorom=False)
    with bind(actor_id="user:qa"), pytest.raises(steps.LibriPlanError) as e:
        steps.pokreni(dok)
    assert e.value.faza == "Čuvar"


@requires_db
@pytest.mark.django_db
def test_cuvar_bez_blokova(db):
    dok = _dok([], document_id="doc_bez_blokova", sa_blokovima=False)
    with bind(actor_id="user:qa"), pytest.raises(steps.LibriPlanError) as e:
        steps.pokreni(dok)
    assert e.value.faza == "Čuvar"


@requires_db
@pytest.mark.django_db
def test_idempotentno(db):
    dok = _dok(["Furnir je tanak list drveta koji se lepi preko osnove."],
               document_id="doc_idem")
    with bind(actor_id="user:qa"):
        prvi = steps.pokreni(dok)
        drugi = steps.pokreni(dok)
    assert (prvi["faze"][0]["rezultat"]["tvrdnje"]
            == drugi["faze"][0]["rezultat"]["tvrdnje"])
