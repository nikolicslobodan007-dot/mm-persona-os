"""Testovi za deploy/aider/pokretac.py. ADR-0086.

Modul se učitava preko putanje (ne preko paketa) jer se vrti izolovano, u
Aiderovom kavezu, i ovde se proverava bez tog okruženja — Aider se nikad
stvarno ne poziva, `_pozovi_aider` se zamenjuje preko monkeypatch.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_POKRETAC_PATH = Path(__file__).resolve().parent.parent / "deploy" / "aider" / "pokretac.py"
_spec = importlib.util.spec_from_file_location("pokretac", _POKRETAC_PATH)
pokretac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pokretac)


class _LazniCoder:
    """Stoji umesto pravog Aiderovog `Coder` objekta u testovima."""

    def __init__(self, **atributi):
        for ime, vrednost in atributi.items():
            setattr(self, ime, vrednost)


def _pripremi_okruzenje(tmp_path):
    radni = tmp_path / "radni"
    radni.mkdir()
    brif = tmp_path / "brif.txt"
    brif.write_text("uradi nesto")
    podesavanja = tmp_path / "podesavanja.yml"
    podesavanja.write_text("{}")
    izvestaj = tmp_path / "izvestaj.json"
    return radni, brif, podesavanja, izvestaj


def _argv_za_pokreni(brif, podesavanja, radni, izvestaj):
    return [
        "--brif", str(brif),
        "--model", "claude-x",
        "--podesavanja", str(podesavanja),
        "--fajl", "a.py",
        "--fajl", "b.py",
        "--citaj", "c.py",
        "--radni", str(radni),
        "--izvestaj", str(izvestaj),
    ]


def test_argv_sadrzi_sve_zastavice_i_file_read_po_ulazu():
    argv = pokretac._sastavi_argv(
        model="claude-x",
        podesavanja="/tmp/podesavanja.yml",
        fajlovi=["a.py", "b.py"],
        citanja=["c.py"],
    )
    assert argv == [
        "--no-git",
        "--model", "claude-x",
        "--model-settings-file", "/tmp/podesavanja.yml",
        "--file", "a.py",
        "--file", "b.py",
        "--read", "c.py",
        "--no-auto-commits",
        "--yes-always",
        "--no-stream",
        "--analytics-disable",
        "--no-check-update",
        "--no-show-model-warnings",
    ]


def test_izvestaj_nosi_tacne_brojeve_iz_laznog_coder_objekta(monkeypatch, tmp_path):
    lazni = _LazniCoder(
        total_tokens_sent=120,
        total_tokens_received=45,
        total_tokens_cache_read=30,
        total_tokens_cache_write=5,
    )
    monkeypatch.setattr(pokretac, "_pozovi_aider", lambda argv, poruka: lazni)

    radni, brif, podesavanja, izvestaj = _pripremi_okruzenje(tmp_path)
    kod = pokretac.pokreni(_argv_za_pokreni(brif, podesavanja, radni, izvestaj))

    assert kod == 0
    podaci = json.loads(izvestaj.read_text())
    assert podaci["model"] == "claude-x"
    assert podaci["tokens_sent"] == 120
    assert podaci["tokens_received"] == 45
    assert podaci["cache_read"] == 30
    assert podaci["cache_write"] == 5
    assert podaci["finish"] == "ok"
    assert podaci["greska"] == ""


def test_brif_stize_kao_tekst_jer_argv_vise_ne_nosi_message_file(monkeypatch, tmp_path):
    """ADR-0089 — sa `return_coder=True` Aider izadje pre petlje razgovora.

    Zato brif mora da stigne kao TEKST, do `coder.run`. Da ovaj test ne postoji,
    pokretač bi opet ćutke podigao kavez, vratio codera i izašao sa kodom 0 —
    bez ijednog poslatog tokena i bez ijedne izmene u fajlu.
    """
    videno = {}

    def _hvataj(argv, poruka):
        videno["argv"], videno["poruka"] = argv, poruka
        return _LazniCoder(total_tokens_sent=1, total_tokens_received=1)

    monkeypatch.setattr(pokretac, "_pozovi_aider", _hvataj)
    radni, brif, podesavanja, izvestaj = _pripremi_okruzenje(tmp_path)
    kod = pokretac.pokreni(_argv_za_pokreni(brif, podesavanja, radni, izvestaj))

    assert kod == 0
    assert videno["poruka"] == "uradi nesto"
    assert "--message-file" not in videno["argv"]
    assert str(brif) not in videno["argv"]


def test_null_a_ne_nula_kad_nema_kes_atribute(monkeypatch, tmp_path):
    lazni = _LazniCoder(total_tokens_sent=10, total_tokens_received=2)
    monkeypatch.setattr(pokretac, "_pozovi_aider", lambda argv, poruka: lazni)

    radni, brif, podesavanja, izvestaj = _pripremi_okruzenje(tmp_path)
    kod = pokretac.pokreni(_argv_za_pokreni(brif, podesavanja, radni, izvestaj))

    assert kod == 0
    podaci = json.loads(izvestaj.read_text())
    assert podaci["cache_read"] is None
    assert podaci["cache_write"] is None


def test_izlazni_kod_razlicit_od_nule_i_greska_popunjena_kad_pozvani_izuzetak(
    monkeypatch, tmp_path
):
    def _puca(argv, poruka):
        raise RuntimeError("nesto je puklo pri pozivu Aidera")

    monkeypatch.setattr(pokretac, "_pozovi_aider", _puca)

    radni, brif, podesavanja, izvestaj = _pripremi_okruzenje(tmp_path)
    kod = pokretac.pokreni(_argv_za_pokreni(brif, podesavanja, radni, izvestaj))

    assert kod != 0
    podaci = json.loads(izvestaj.read_text())
    assert podaci["finish"] == "greska"
    assert podaci["greska"] == "nesto je puklo pri pozivu Aidera"
