"""Testovi LLM ekstraktora entiteta i odnosa (ADR-0031 sloj 4b, pojačavač).

Iste tvrde granice se mere u gejtu kao kod `ekstrakt` za tvrdnje:
  1. Filter uzemljenja: entitet mora da citira postojeći block_id i da mu naziv
     bude u tom bloku (preklapanje ≥ _PRAG), vrsta iz vokabulara; odnos opstaje
     samo između dva uzemljena entiteta, oba u citiranom bloku, tip iz vokabulara.
     Halucinacija (lažan block_id, nova reč, nepoznata vrsta/tip, veza van
     entiteta) ne prolazi (Canon §10.4).
  2. Kad je spoljni model isključen, ekstrakt daje IDENTIČAN rezultat kao
     deterministička osnova (`entiteti.izvuci_*`) — sistem radi bez ijednog ključa.
Poziv modela se ne testira mrežom: izlaz modela se ubacuje kao tekst.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from api.context import bind
from apps.libri import ekstrakt_entiteti, entiteti
from apps.libri.models import Block, Entitet, LibriDocument, Odnos
from apps.memory.models import KnowledgeSource
from common import enums as E
from tests.conftest import requires_db


def _blok(text, *, i=1, block_type="paragraph"):
    return SimpleNamespace(block_type=block_type, text=text,
                           block_id=f"blk_{i:06d}", source_page=1)


def _dok_sa_izvorom(recenice, *, document_id="doc_graf_llm"):
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


# ---- parse (čista funkcija, bez baze) ----

def test_parse_objekat_iz_omota():
    txt = ('Evo:\n```json\n{"entiteti":[{"naziv":"Vinogradi","vrsta":"organizacija",'
           '"block_id":"blk_000001"}],"odnosi":[]}\n```')
    ent, odn = ekstrakt_entiteti._parse(txt)
    assert len(ent) == 1 and odn == []
    assert ent[0]["naziv"] == "Vinogradi"
    assert ent[0]["vrsta"] == "organizacija"
    assert ent[0]["block_id"] == "blk_000001"


def test_parse_smece_vraca_prazno():
    assert ekstrakt_entiteti._parse("nije json") == ([], [])
    assert ekstrakt_entiteti._parse("") == ([], [])
    assert ekstrakt_entiteti._parse("[1,2,3]") == ([], [])  # lista nije naš oblik


# ---- filter uzemljenja: entiteti ----

def test_uzemljenje_entiteta_baca_halucinaciju():
    blok = _blok("Milan Jovanović radi u kompaniji Vinogradi.", i=1)
    kand = [
        {"naziv": "Milan Jovanović", "vrsta": "osoba", "block_id": "blk_000001"},
        # reči van bloka → baca:
        {"naziv": "Zmaj Leteći", "vrsta": "osoba", "block_id": "blk_000001"},
        # vrsta van vokabulara → baca:
        {"naziv": "Vinogradi", "vrsta": "mesto", "block_id": "blk_000001"},
        # lažan block_id → baca:
        {"naziv": "Milan Jovanović", "vrsta": "osoba", "block_id": "blk_999999"},
    ]
    uz = ekstrakt_entiteti._uzemlji_entitete(kand, [blok])
    assert [(e["name"], e["kind"]) for e in uz] == [("Milan Jovanović", "osoba")]
    assert uz[0]["block_id"] == "blk_000001"
    assert uz[0]["source_page"] == 1
    assert uz[0]["confidence"] == 0.7


def test_uzemljenje_entiteta_bez_duplikata():
    blok = _blok("Firma Vinogradi je osnovana davno.", i=1)
    kand = [
        {"naziv": "Vinogradi", "vrsta": "organizacija", "block_id": "blk_000001"},
        {"naziv": "vinogradi", "vrsta": "organizacija", "block_id": "blk_000001"},
    ]
    assert len(ekstrakt_entiteti._uzemlji_entitete(kand, [blok])) == 1


def test_uzemljenje_dogadjaja_uzima_datum_iz_bloka():
    blok = _blok("Sajam Drvo održan je 12.03.2026. godine.", i=1)
    kand = [{"naziv": "Sajam Drvo", "vrsta": "dogadjaj", "block_id": "blk_000001"}]
    uz = ekstrakt_entiteti._uzemlji_entitete(kand, [blok])
    assert len(uz) == 1
    assert uz[0]["desilo_se"] == "2026-03-12"   # datum iz bloka, ne od modela
    assert uz[0]["objavljeno"] is None


# ---- filter uzemljenja: odnosi ----

def test_uzemljenje_odnosa_samo_izmedju_uzemljenih():
    blok = _blok("Ana Petrović je direktorka preduzeća Drvo Promet.", i=1)
    ent_kand = [
        {"naziv": "Ana Petrović", "vrsta": "osoba", "block_id": "blk_000001"},
        {"naziv": "Drvo Promet", "vrsta": "organizacija", "block_id": "blk_000001"},
    ]
    uz_e = ekstrakt_entiteti._uzemlji_entitete(ent_kand, [blok])
    odn_kand = [
        {"subjekat": "Ana Petrović", "objekat": "Drvo Promet", "tip": "vodi",
         "block_id": "blk_000001"},                                   # oba uzemljena → ostaje
        {"subjekat": "Ana Petrović", "objekat": "Nepoznati Lik", "tip": "vodi",
         "block_id": "blk_000001"},                                   # objekat nije entitet → baca
        {"subjekat": "Ana Petrović", "objekat": "Drvo Promet", "tip": "saradjuje",
         "block_id": "blk_000001"},                                   # tip van vokabulara → baca
    ]
    uz_o = ekstrakt_entiteti._uzemlji_odnose(odn_kand, uz_e, [blok])
    assert [(o["subject"], o["relation_type"], o["object"]) for o in uz_o] == \
        [("Ana Petrović", "vodi", "Drvo Promet")]
    assert uz_o[0]["confidence"] == 0.7


def test_iz_teksta_spaja_entitete_i_odnose():
    blok = _blok("Marko Ilić je osnovao kompaniju Tipl Sistem.", i=1)
    txt = ('{"entiteti":['
           '{"naziv":"Marko Ilić","vrsta":"osoba","block_id":"blk_000001"},'
           '{"naziv":"Tipl Sistem","vrsta":"organizacija","block_id":"blk_000001"}],'
           '"odnosi":[{"subjekat":"Marko Ilić","objekat":"Tipl Sistem",'
           '"tip":"osnovao","block_id":"blk_000001"}]}')
    uz_e, uz_o = ekstrakt_entiteti._iz_teksta(txt, [blok])
    assert {(e["name"], e["kind"]) for e in uz_e} == \
        {("Marko Ilić", "osoba"), ("Tipl Sistem", "organizacija")}
    assert [(o["subject"], o["relation_type"], o["object"]) for o in uz_o] == \
        [("Marko Ilić", "osnovao", "Tipl Sistem")]


# ---- fallback ugovor (LLM isključen → identično osnovi) ----

@requires_db
@pytest.mark.django_db
def test_izvuci_bez_modela_jednak_osnovi(db):
    blokovi = [
        _blok("Milan Jovanović radi u kompaniji Vinogradi.", i=1),
        _blok("Ana Petrović je direktorka preduzeća Drvo Promet.", i=2),
    ]
    osnova_e = entiteti.izvuci_entitete(blokovi)
    osnova_o = entiteti.izvuci_odnose(blokovi, osnova_e)
    assert ekstrakt_entiteti.izvuci(blokovi) == (osnova_e, osnova_o)


@requires_db
@pytest.mark.django_db
def test_meri_bez_modela_ne_zove(db):
    d = ekstrakt_entiteti.meri([_blok("Milan Jovanović radi u kompaniji Vinogradi.", i=1)])
    assert d["model_zvan"] is False
    assert d["entiteti_sirovo"] == 0
    assert d["odnosi_sirovo"] == 0


@requires_db
@pytest.mark.django_db
def test_upisi_bez_modela_pise_kao_osnova(db):
    dok, izvor = _dok_sa_izvorom([
        "Milan Jovanović radi u kompaniji Vinogradi.",
        "Brušenje se radi u nekoliko prolaza.",  # bez entiteta
    ])
    with bind(actor_id="user:qa"):
        rez = ekstrakt_entiteti.upisi(dok)
    assert rez == {"entiteta": 2, "odnosa": 1, "obrisano": 0}
    assert Entitet.objects.filter(source=izvor).count() == 2
    odnos = Odnos.objects.get(source=izvor)
    assert odnos.relation_type == "radi_u"
    assert odnos.subject.name == "Milan Jovanović"
    assert odnos.object.name == "Vinogradi"
