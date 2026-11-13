"""Test podataka Pojmovnika struke (ADR-0156) — čist, nad .jsonl datotekama."""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "apps" / "content" / "data"
VINO = DATA / "pojmovnik-vino-rakija.jsonl"
METRO = DATA / "pojmovnik-metrologija.jsonl"


def _ucitaj(p: Path) -> list[dict]:
    return [json.loads(r) for r in p.read_text(encoding="utf-8").splitlines() if r]


def test_datoteke_postoje():
    assert VINO.exists() and METRO.exists()


def test_svaki_red_ima_polja():
    for p in (VINO, METRO):
        for r in _ucitaj(p):
            assert r["termin"] and r["domen"] and r["definicija"]
            assert isinstance(r["sinonimi"], list)


def test_buke_je_u_pojmovniku():
    termini = {r["termin"] for r in _ucitaj(VINO)}
    assert "buke" in termini  # motiv cele priče: tačan vinski termin


def test_metrologija_ima_broj_tacke():
    for r in _ucitaj(METRO):
        assert r["domen"] == "metrologija"
        assert r["izvor"].startswith("VIML")


def test_broj_termina():
    assert len(_ucitaj(VINO)) == 50
    assert len(_ucitaj(METRO)) == 44
