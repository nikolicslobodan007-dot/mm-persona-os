"""Test podataka Propisa (ADR-0157) — čist, nad .jsonl datotekom zakona."""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "apps" / "content" / "data"
METROLOGIJA = DATA / "propisi-zakon-o-metrologiji.jsonl"


def _ucitaj(p: Path) -> list[dict]:
    return [json.loads(r) for r in p.read_text(encoding="utf-8").splitlines() if r]


def test_datoteka_postoji():
    assert METROLOGIJA.exists()


def test_svaki_red_ima_polja():
    for r in _ucitaj(METROLOGIJA):
        assert r["propis"] and r["sl_glasnik"] and r["glava"]
        assert isinstance(r["clan"], int) and r["clan"] >= 1
        assert r["tekst"].strip()


def test_svih_62_clanova_prisutno():
    brojevi = sorted(r["clan"] for r in _ucitaj(METROLOGIJA))
    assert brojevi == list(range(1, 63))


def test_sedamnaest_glava():
    glave = {r["glava"] for r in _ucitaj(METROLOGIJA)}
    assert len(glave) == 17


def test_poznati_clan_ima_ocekivani_naslov():
    po_broju = {r["clan"]: r for r in _ucitaj(METROLOGIJA)}
    assert po_broju[1]["naslov"] == "Predmet"
    assert po_broju[26]["naslov"].startswith("Obaveze vlasnika")
    assert "metrologije" in po_broju[1]["tekst"].lower()


def test_broj_iz_upita_prepoznaje_clan():
    from apps.content import propisi
    assert propisi._broj_iz_upita("šta kaže član 26?") == 26
    assert propisi._broj_iz_upita("po članu 44 inspektor") == 44
    assert propisi._broj_iz_upita("nema broja ovde") is None
