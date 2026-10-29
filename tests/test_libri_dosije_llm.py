"""Testovi LLM analize dosija — hipoteze (§9) i otvorena pitanja (§10), ADR-0031 4c.

§9/§10 su INFERRED (sinteza), ne OBSERVED — zato NEMA filtera doslovnog
uzemljenja. Brana je drugačija i meri se ovde:
  1. Svaka stavka mora da se osloni na bar jedan POSTOJEĆI block_id; izmišljene
     reference se bacaju, a stavka bez ijednog postojećeg oslonca se baca.
  2. Bez spoljne rute (model isključen) → sekcije 9/10 ostaju „—" (deterministička
     osnova), a `analiza` vraća prazne liste (fallback ugovor).
Poziv modela se ne testira mrežom: izlaz modela se ubacuje kao tekst.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from api.context import bind
from apps.libri import analiza, dosije, tvrdnje
from apps.libri.models import Block, LibriDocument
from apps.memory.models import KnowledgeSource
from common import enums as E
from tests.conftest import requires_db


def _baza(**extra):
    d = {
        "naslov": "Proba", "document_id": "doc_x", "poreklo": "izvor",
        "blokova": 2, "tvrdnje": [{"subject": "Furnir", "relacija": "je",
                                   "vrednost": "tanak list", "block_id": "blk_000001"}],
        "akteri": [], "dogadjaji": [], "dokazi": [], "odnosi": [],
        "kontradikcije": [], "hronologija": [],
        "pouzdanost": {"pouzdanost": 0.0, "nezavisnost": 0.0, "blizina": 0.0,
                       "potkrepljenost": 0.0, "stabilnost": 0.0, "ukupno": 0.0, "broj": 0},
        "blok_idovi": ["blk_000001", "blk_000002"],
    }
    d.update(extra)
    return d


# ---- parse (čista funkcija) ----

def test_parse_objekat_iz_omota():
    txt = ('```json\n{"hipoteze":[{"tekst":"H1","oslonac":["blk_000001"]}],'
           '"pitanja":[{"tekst":"P1","oslonac":["blk_000002"]}]}\n```')
    h, p = analiza._parse(txt)
    assert [x["tekst"] for x in h] == ["H1"]
    assert [x["tekst"] for x in p] == ["P1"]
    assert h[0]["oslonac"] == ["blk_000001"]


def test_parse_smece_vraca_prazno():
    assert analiza._parse("nije json") == ([], [])
    assert analiza._parse("") == ([], [])
    assert analiza._parse("[1,2,3]") == ([], [])


# ---- brana oslonca ----

def test_uzemlji_baca_bez_postojeceg_oslonca():
    vb = {"blk_000001"}
    stavke = [
        {"tekst": "H valid", "oslonac": ["blk_000001"]},          # ostaje
        {"tekst": "H izmisljen", "oslonac": ["blk_999999"]},      # sve reference lazne → baca
        {"tekst": "H bez", "oslonac": []},                        # nema oslonca → baca
        {"tekst": "H valid", "oslonac": ["blk_000001"]},          # duplikat → jednom
    ]
    out = analiza._uzemlji(stavke, vb)
    assert [s["tekst"] for s in out] == ["H valid"]
    assert out[0]["oslonac"] == ["blk_000001"]


def test_uzemlji_filtrira_izmisljene_a_zadrzi_postojece():
    vb = {"blk_000001"}
    out = analiza._uzemlji(
        [{"tekst": "H", "oslonac": ["blk_000001", "blk_999999"]}], vb)
    assert len(out) == 1
    assert out[0]["oslonac"] == ["blk_000001"]   # lažan block_id otpada, pravi ostaje


def test_iz_teksta_spaja_hipoteze_i_pitanja():
    txt = ('{"hipoteze":[{"tekst":"Sušenje utiče na kvalitet","oslonac":["blk_000001"]},'
           '{"tekst":"Lebdi","oslonac":["blk_777777"]}],'
           '"pitanja":[{"tekst":"Koji režim sušenja?","oslonac":["blk_000002"]}]}')
    h, p = analiza._iz_teksta(txt, {"blk_000001", "blk_000002"})
    assert [x["tekst"] for x in h] == ["Sušenje utiče na kvalitet"]   # "Lebdi" otpalo
    assert [x["tekst"] for x in p] == ["Koji režim sušenja?"]


# ---- markdown §9/§10 ----

def test_markdown_renderuje_hipoteze_i_pitanja():
    md = dosije._markdown(_baza(
        hipoteze=[{"tekst": "Hipoteza A", "oslonac": ["blk_000001"]}],
        pitanja=[{"tekst": "Pitanje B", "oslonac": ["blk_000002"]}]))
    assert "## 9. Konkurentske hipoteze" in md
    assert "Hipoteza A" in md
    assert "## 10. Otvorena pitanja" in md
    assert "Pitanje B" in md
    assert "INFERRED" in md                 # jasno označeno da nije OBSERVED
    assert "blk_000001" in md               # oslonac vidljiv


def test_markdown_bez_llm_zadrzava_crtice():
    md = dosije._markdown(_baza())          # bez hipoteza/pitanja
    assert "## 9. Konkurentske hipoteze" in md
    assert "## 10. Otvorena pitanja" in md
    assert "dolazi sa LLM slojem" in md     # determinističke „—" linije


# ---- fallback ugovor (model isključen) ----

def _dok(recenice, *, document_id="doc_analiza"):
    izvor = KnowledgeSource.objects.create(
        persona=None, title="Analiza izvor",
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


@requires_db
@pytest.mark.django_db
def test_analiza_bez_modela_prazno(db):
    prikup = {"tvrdnje": [{"subject": "Furnir", "relacija": "je",
                           "vrednost": "tanak list", "block_id": "blk_000001"}]}
    assert analiza.analiza(prikup, {"blk_000001"}) == {"hipoteze": [], "pitanja": []}


@requires_db
@pytest.mark.django_db
def test_meri_bez_modela_ne_zove(db):
    prikup = {"tvrdnje": [{"subject": "X", "relacija": "je", "vrednost": "y",
                           "block_id": "blk_000001"}]}
    d = analiza.meri(prikup, {"blk_000001"})
    assert d["model_zvan"] is False
    assert d["hipoteze"] == 0 and d["pitanja"] == 0


@requires_db
@pytest.mark.django_db
def test_sastavi_llm_bez_modela_zadrzava_crtice(db):
    dok, _ = _dok(["Furnir je tanak list drveta koji se lepi preko osnove."])
    with bind(actor_id="user:qa"):
        tvrdnje.upisi(dok)
    md = dosije.sastavi(dok, llm=True)       # llm tražen, ali nema rute → „—"
    assert "## 9. Konkurentske hipoteze" in md
    assert "## 10. Otvorena pitanja" in md
    assert "dolazi sa LLM slojem" in md
    assert "INFERRED — LLM" not in md        # ništa izmišljeno bez modela
