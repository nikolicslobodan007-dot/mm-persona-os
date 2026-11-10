"""ADR-0131 — promocija veština po domenu (niši) persone.

Čiste jedinične provere helpera (bez baze i modela) + jedna integraciona nad
`mila` fixturom: niša `sales 0.7` diže prodajnu veštinu iznad semantički bliže
inženjerske, a bez persone (bez niša) ostaje čist kosinus (no-op fallback).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.conf import settings

from apps.memory import context, embeddings
from apps.memory.vestine import Vestina, uvezi
from common import enums as E
from tests.conftest import requires_db

DIM = settings.VESTINA_EMBEDDING_DIM
#: isti marker u upitu i u veštini → isti vektor → kosinusna razdaljina 0.
MARKERI = {"alfa": 0, "beta": 1}


def _laz_vektor(text: str, *, model=None):
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


def _fakt(napomene: str):
    return SimpleNamespace(object_json={"napomene": napomene})


def test_divizija_iz_napomene():
    assert context._divizija_vestine(
        _fakt("Destilovano iz agency-agents/sales/foo.md (MIT) — naš opis.")) == "sales"
    assert context._divizija_vestine(
        _fakt("Destilovano iz agency-agents/paid-media/x.md (MIT)")) == "paid-media"
    # GitHub Signals izvor nema diviziju → prazno, pa nema podsticaja
    assert context._divizija_vestine(
        _fakt("Sakupljeno iz web: https://github.com/a/b — naš opis.")) == ""
    assert context._divizija_vestine(_fakt("")) == ""


def test_promovisi_dize_nisu(monkeypatch):
    monkeypatch.setattr(context, "_persona_divizije", lambda p: {"sales": 0.7})
    eng = _fakt("Destilovano iz agency-agents/engineering/a.md (MIT)")
    gh = _fakt("Sakupljeno iz web: https://github.com/a/b")
    sal = _fakt("Destilovano iz agency-agents/sales/b.md (MIT)")
    out = context._promovisi_domen("persona", [eng, gh, sal])  # kosinusni ulaz
    assert out[0] is sal            # prodajna niša podiže sales diviziju na vrh
    assert out[1:] == [eng, gh]     # ostatak ostaje stabilno, kako je ušao


def test_bez_nisa_ne_dira(monkeypatch):
    monkeypatch.setattr(context, "_persona_divizije", lambda p: {})
    a = _fakt("agency-agents/sales/x")
    b = _fakt("agency-agents/engineering/y")
    assert context._promovisi_domen("p", [a, b]) == [a, b]


def test_genericka_nisa_ne_gura(monkeypatch):
    # `ai`/`b2b` nemaju odgovarajuću diviziju → ne menjaju poredak (namera ADR-a)
    monkeypatch.setattr(context, "_persona_divizije",
                        lambda p: {"ai": 0.9, "b2b": 0.9})
    eng = _fakt("Destilovano iz agency-agents/engineering/a.md (MIT)")
    sal = _fakt("Destilovano iz agency-agents/sales/b.md (MIT)")
    assert context._promovisi_domen("p", [eng, sal]) == [eng, sal]


@requires_db
@pytest.mark.django_db
def test_nisa_persone_dize_prodajnu_vestinu(mila, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    uvezi(naslov_izvora="agency-agents – engineering (destilovano)",
          uri="https://example.com/eng", license_box=E.LicenseBox.SLOBODNA,
          license_note="MIT", actor="user:qa",
          vestine=[Vestina(
              ime="eng-vestina", koraci=["uradi alfa"], pouzdanost=0.9,
              napomene="Destilovano iz agency-agents/engineering/a.md (MIT) — naš opis.")])
    uvezi(naslov_izvora="agency-agents – sales (destilovano)",
          uri="https://example.com/sales", license_box=E.LicenseBox.SLOBODNA,
          license_note="MIT", actor="user:qa",
          vestine=[Vestina(
              ime="sales-vestina", koraci=["uradi nesto"], pouzdanost=0.9,
              napomene="Destilovano iz agency-agents/sales/b.md (MIT) — naš opis.")])

    # eng je semantički bliži (marker `alfa`), ali Milina niša `sales` ga preskače
    subj = [f.subject for f in context._rangiraj_vestine(mila, "treba mi zadatak alfa", "")]
    assert subj.index("sales-vestina") < subj.index("eng-vestina")

    # bez persone (bez niša) → čist kosinus: eng prvi (no-op fallback)
    bez = [f.subject for f in context._rangiraj_vestine(None, "treba mi zadatak alfa", "")]
    assert bez.index("eng-vestina") < bez.index("sales-vestina")


@requires_db
@pytest.mark.django_db
def test_najbliza_distanca_i_broj_u_diviziji(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    uvezi(naslov_izvora="agency-agents – sales (destilovano)",
          uri="https://example.com/s", license_box=E.LicenseBox.SLOBODNA,
          license_note="MIT", actor="user:qa",
          vestine=[Vestina(
              ime="s1", koraci=["uradi alfa"], pouzdanost=0.9,
              napomene="Destilovano iz agency-agents/sales/a.md (MIT)")])
    uvezi(naslov_izvora="agency-agents – engineering (destilovano)",
          uri="https://example.com/e", license_box=E.LicenseBox.SLOBODNA,
          license_note="MIT", actor="user:qa",
          vestine=[Vestina(
              ime="e1", koraci=["uradi beta"], pouzdanost=0.9,
              napomene="Destilovano iz agency-agents/engineering/b.md (MIT)")])

    # tema sa markerom `alfa` → s1 ima identičan vektor → najbliža ~0
    d = context.najbliza_distanca("treba mi alfa")
    assert d is not None and d < 0.01
    assert context.broj_u_diviziji("sales") == 1
    assert context.broj_u_diviziji("engineering") == 1
    assert context.broj_u_diviziji("marketing") == 0  # prazno = praznina
    assert context.broj_u_diviziji("") == 0


@requires_db
@pytest.mark.django_db
def test_najbliza_distanca_offline_vraca_none(monkeypatch):
    def pukni(text, *, model=None):
        raise RuntimeError("offline")

    monkeypatch.setattr(embeddings, "embed_semanticki", pukni)
    assert context.najbliza_distanca("bilo šta") is None


def test_praznina_logika():
    from apps.memory.management.commands.potraznja import _praznina
    # pokriveno divizijom (sales: 36 veština) — NIJE praznina ni uz golu reč
    assert _praznina(36, 0.482, 0.45) is False
    # pokriveno semantički (AI: nema divizije, ali najbliža 0.398 < prag)
    assert _praznina(0, 0.398, 0.45) is False
    # ni divizije ni bliske veštine → praznina (B2B: 0.664)
    assert _praznina(0, 0.664, 0.45) is True
    # model offline: odlučuje samo divizija
    assert _praznina(0, None, 0.45) is True
    assert _praznina(5, None, 0.45) is False
