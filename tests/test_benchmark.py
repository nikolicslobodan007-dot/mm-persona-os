"""Testovi za WK Model Benchmark motor (ADR-0150).

Čisti testovi: determinističke provere, obračun cene i agregacija (zbir).
Ne diraju bazu ni gateway — mere da je sam metar ispravan.
"""

from __future__ import annotations

from apps.llm_gateway import benchmark as B

# ---------------------------------------------------------------- provere

def test_json_tip_prihvata_dozvoljeni():
    assert B._json_tip('{"tip": "kupac"}', {"kupac", "dobavljac"}) is True


def test_json_tip_odbija_nedozvoljeni():
    assert B._json_tip('{"tip": "nesto"}', {"kupac"}) is False


def test_json_tip_vadi_json_iz_sireg_teksta():
    assert B._json_tip('Evo: {"tip": "KONKURENT"} eto.', {"konkurent"}) is True


def test_json_tip_odbija_bez_jsona():
    assert B._json_tip("nema ovde json", {"kupac"}) is False
    assert B._json_tip("", {"kupac"}) is False


def test_json_tip_odbija_pokvaren_json():
    assert B._json_tip('{"tip": kupac}', {"kupac"}) is False


def test_ima_dijakritiku():
    assert B._ima_dijakritiku("berba grožđa je počela") is True
    assert B._ima_dijakritiku("obicna recenica bez kvaka") is False
    assert B._ima_dijakritiku("") is False


def test_tacno_tri_reda():
    assert B._tacno_tri_reda("prvi\ndrugi\ntreci") is True
    assert B._tacno_tri_reda("prvi\n\ndrugi\n\ntreci\n") is True  # prazni ne broje
    assert B._tacno_tri_reda("prvi\ndrugi") is False
    assert B._tacno_tri_reda("a\nb\nc\nd") is False


def test_sadrzi():
    assert B._sadrzi("Marko Jović iz Novog Sada", "marko", "novog sada") is True
    assert B._sadrzi("Marko iz Beograda", "marko", "novog sada") is False


# ---------------------------------------------------------------- cena

def test_cena_usd_poznat_model():
    # sonnet-5: ulaz 2$/1M, izlaz 10$/1M → 1000 ul + 500 izl
    c = B.cena_usd("anthropic:claude-sonnet-5", 1000, 500)
    assert abs(c - (1000 / 1e6 * 2.0 + 500 / 1e6 * 10.0)) < 1e-12


def test_cena_usd_nepoznat_model_nula():
    assert B.cena_usd("niko:nista", 1000, 1000) == 0.0


def test_cena_usd_jeftin_vs_skup():
    jeftin = B.cena_usd("anthropic:claude-haiku-5.5", 1000, 1000)
    skup = B.cena_usd("anthropic:claude-opus-5.5", 1000, 1000)
    assert skup > jeftin


# ---------------------------------------------------------------- zbir

def _rez(spec, kat, uspeh, tin=1000, tout=500, ms=100, greska=""):
    return B.Rezultat(spec=spec, kljuc="k", kategorija=kat, uspeh=uspeh,
                      tin=tin, tout=tout, ms=ms, greska=greska)


def test_zbir_broji_i_stopu():
    rez = [
        _rez("anthropic:claude-sonnet-5", "CRM/JSON", True),
        _rez("anthropic:claude-sonnet-5", "Format", False),
        _rez("anthropic:claude-sonnet-5", "Srpski jezik", True),
    ]
    z = B.zbir(rez)["anthropic:claude-sonnet-5"]
    assert z.n == 3
    assert z.prosli == 2
    assert abs(z.stopa - 2 / 3) < 1e-9


def test_zbir_cena_po_uspehu_deli_samo_prosle():
    rez = [
        _rez("anthropic:claude-sonnet-5", "CRM/JSON", True),
        _rez("anthropic:claude-sonnet-5", "Format", False),
    ]
    z = B.zbir(rez)["anthropic:claude-sonnet-5"]
    # ukupna cena 2 poziva deljena sa 1 uspehom
    assert abs(z.cena_po_uspehu - z.cena_usd / 1) < 1e-12


def test_zbir_cena_po_uspehu_beskonacno_kad_nema_uspeha():
    z = B.zbir([_rez("x:y", "K", False)])["x:y"]
    assert z.cena_po_uspehu == float("inf")


def test_zbir_ms_prosek_i_greske():
    rez = [
        _rez("x:y", "K", True, ms=100),
        _rez("x:y", "K", False, ms=300, greska="timeout"),
    ]
    z = B.zbir(rez)["x:y"]
    assert z.ms_prosek == 200
    assert z.greske == 1


def test_zbir_po_kategoriji():
    rez = [
        _rez("x:y", "CRM/JSON", True),
        _rez("x:y", "CRM/JSON", False),
        _rez("x:y", "Format", True),
    ]
    z = B.zbir(rez)["x:y"]
    assert z.po_kategoriji["CRM/JSON"] == (1, 2)
    assert z.po_kategoriji["Format"] == (1, 1)


def test_zbir_razdvaja_modele():
    rez = [
        _rez("a:1", "K", True),
        _rez("b:2", "K", False),
    ]
    z = B.zbir(rez)
    assert set(z) == {"a:1", "b:2"}
    assert z["a:1"].prosli == 1
    assert z["b:2"].prosli == 0


# ---------------------------------------------------------------- slučajevi (sanity)

def test_slucajevi_imaju_proveru_i_jedinstvene_kljuceve():
    kljucevi = [s.kljuc for s in B.SLUCAJEVI]
    assert len(kljucevi) == len(set(kljucevi))
    for s in B.SLUCAJEVI:
        assert callable(s.proveri)
        assert s.system and s.prompt
