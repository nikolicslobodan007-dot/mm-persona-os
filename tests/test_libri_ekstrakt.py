"""Testovi LLM ekstraktora tvrdnji (ADR-0031 sloj 4a, opcija B).

Dve tvrde granice se mere u gejtu:
  1. Filter uzemljenja (preklapanje reči ≥ _PRAG) baca reči kojih nema u bloku —
     halucinacija (lažan block_id ili nova reč) ne prolazi (Canon §10.4), ali
     preraspored / izostavljena pomoćna reč prolazi (tolerancija za odziv).
  2. Kad je spoljni model isključen, ekstrakt daje IDENTIČAN rezultat kao
     deterministička osnova (fallback ugovor) — sistem radi bez ijednog ključa.
Poziv modela se ne testira mrežom: izlaz modela se ubacuje kao tekst.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from api.context import bind
from apps.libri import ekstrakt, tvrdnje
from apps.libri.models import Block, LibriDocument
from apps.memory.models import KnowledgeFact, KnowledgeSource
from common import enums as E
from tests.conftest import requires_db


def _blok(text, *, i=1, block_type="paragraph"):
    return SimpleNamespace(block_type=block_type, text=text,
                           block_id=f"blk_{i:06d}", source_page=1)


# ---- parse + preklapanje (čiste funkcije, bez baze) ----

def test_parse_json_iz_omota():
    txt = ('Evo rezultata:\n```json\n[{"subject":"Furnir","relacija":"je",'
           '"vrednost":"tanak list drveta","block_id":"blk_000001"}]\n```')
    kand = ekstrakt._parse(txt)
    assert len(kand) == 1
    assert kand[0]["subject"] == "Furnir"
    assert kand[0]["block_id"] == "blk_000001"


def test_parse_smece_vraca_praznu_listu():
    assert ekstrakt._parse("nije json") == []
    assert ekstrakt._parse("") == []


def test_preklapanje_racuna_udeo_reci():
    blok = set(ekstrakt._tokeni("Furnir je tanak list drveta koji se lepi."))
    assert ekstrakt._preklapanje("tanak list drveta", blok) == 1.0
    assert ekstrakt._preklapanje("list tanak", blok) == 1.0          # preraspored
    assert ekstrakt._preklapanje("električni list", blok) == 0.5     # jedna nova reč


# ---- filter uzemljenja ----

def test_uzemljenje_zadrzava_doslovno_a_baca_halucinaciju():
    blok = _blok("Furnir je tanak list drveta koji se lepi preko osnove.", i=1)
    txt = (
        '[{"subject":"Furnir","relacija":"je","vrednost":"tanak list drveta",'
        '"block_id":"blk_000001"},'                        # uzemljeno → ostaje
        '{"subject":"Zmaj","relacija":"je","vrednost":"leteća zver",'
        '"block_id":"blk_000001"},'                        # nove reči → baca
        '{"subject":"Furnir","relacija":"je","vrednost":"tanak list drveta",'
        '"block_id":"blk_999999"}]'                        # lažan block_id → baca
    )
    kand = ekstrakt._iz_teksta(txt, [blok])
    assert len(kand) == 1
    assert kand[0]["subject"] == "Furnir"
    assert kand[0]["block_id"] == "blk_000001"
    assert kand[0]["source_page"] == 1
    assert kand[0]["confidence"] == 0.7


def test_uzemljenje_tolerise_preraspored_a_baca_novu_rec():
    blok = _blok("Rende je ručni alat koji skida tanak sloj drveta.", i=1)
    txt = ('[{"subject":"Rende","relacija":"je","vrednost":"alat ručni",'
           '"block_id":"blk_000001"},'                      # preraspored → ostaje
           '{"subject":"Rende","relacija":"je","vrednost":"električni alat",'
           '"block_id":"blk_000001"}]')                     # nova reč → baca
    kand = ekstrakt._iz_teksta(txt, [blok])
    assert len(kand) == 1
    assert kand[0]["vrednost"] == "alat ručni"


def test_uzemljenje_bez_duplikata():
    blok = _blok("Lak je zaštitni premaz za drvene površine.", i=1)
    txt = ('[{"subject":"Lak","relacija":"je","vrednost":"zaštitni premaz",'
           '"block_id":"blk_000001"},'
           '{"subject":"Lak","relacija":"je","vrednost":"zaštitni premaz",'
           '"block_id":"blk_000001"}]')
    assert len(ekstrakt._iz_teksta(txt, [blok])) == 1


# ---- fallback ugovor (LLM isključen → identično osnovi) ----

@requires_db
@pytest.mark.django_db
def test_izvuci_bez_modela_jednak_osnovi(db):
    blokovi = [
        _blok("Furnir je tanak list drveta koji se lepi preko osnove.", i=1),
        _blok("Rende je ručni alat koji skida tanak sloj drveta.", i=2),
    ]
    assert ekstrakt.izvuci(blokovi) == tvrdnje.izvuci(blokovi)


@requires_db
@pytest.mark.django_db
def test_meri_bez_modela_ne_zove(db):
    d = ekstrakt.meri([_blok("Furnir je tanak list drveta.", i=1)])
    assert d["model_zvan"] is False
    assert d["sirovo"] == 0


@requires_db
@pytest.mark.django_db
def test_upisi_bez_modela_pise_kao_osnova(db):
    izvor = KnowledgeSource.objects.create(
        persona=None, title="E izvor",
        source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
        trust_score=Decimal("1.000"))
    dok = LibriDocument.objects.create(
        source=izvor, document_id="doc_ekstrakt", version_id="v1", title="T",
        language="sr-Latn", script="latin", pages=1, schema_version="lkp-0.1",
        ingested_at=timezone.now())
    Block.objects.bulk_create([
        Block(document=dok, block_id="blk_000001", block_type="paragraph",
              text="Furnir je tanak list drveta koji se lepi preko osnove.",
              language="sr-Latn", order=1, extraction_confidence=Decimal("0.9")),
    ])
    with bind(actor_id="user:qa"):
        rez = ekstrakt.upisi(dok)
    assert rez["upisano"] == 1
    cinjenice = KnowledgeFact.objects.filter(source=izvor, predicate=tvrdnje.PREDIKAT)
    assert cinjenice.count() == 1
    assert cinjenice.first().provenance == E.Provenance.OBSERVED.value
