"""ADR-0142 — direktor bira FORMAT pisanja; dug format dobija svoj budžet."""

from __future__ import annotations

from types import SimpleNamespace

from apps.content import zadaci
from apps.orchestration import razgovor as nit


def test_procitaj_odluku_prima_format():
    d = nit._procitaj_odluku('{"vrsta":"dubinski-clanak"}', {"UPRAVA"})
    assert d["vrsta"] == "dubinski-clanak"
    # nepoznat format → objava
    assert nit._procitaj_odluku('{"vrsta":"nesto"}', {"UPRAVA"})["vrsta"] == "objava"
    # interni (battlecard) NIJE dozvoljena vrsta kroz razgovor → objava
    assert nit._procitaj_odluku('{"vrsta":"battlecard"}', {"UPRAVA"})["vrsta"] == "objava"


def test_koraci_dug_format_ide_u_content_draft():
    sef = SimpleNamespace(display_name="Šef", public_id="P-10")
    izv = SimpleNamespace(display_name="Izv", public_id="P-11")
    plosnato = str(nit._koraci("piši članak", sef, izv, vrsta="dubinski-clanak"))
    assert "content.draft" in plosnato
    assert "dubinski-clanak" in plosnato  # format stigao do koraka


def test_koraci_objava_nema_format_u_ulazu():
    sef = SimpleNamespace(display_name="Šef", public_id="P-10")
    izv = SimpleNamespace(display_name="Izv", public_id="P-11")
    plosnato = str(nit._koraci("piši objavu", sef, izv))  # default objava
    assert "content.draft" in plosnato
    assert "dubinski-clanak" not in plosnato
    assert "'vrsta'" not in plosnato  # objava ne kači Zadatak


def test_dozvoljene_vrste_sadrzi_formate_ne_interne():
    doz = nit._dozvoljene_vrste()
    assert {"objava", "dubinski-clanak", "nit", "newsletter", "video-scenario"} <= doz
    assert "prepis-videa" in doz and "sazetak-weba" in doz
    assert "battlecard" not in doz  # interni se ne rutira kroz razgovor


def test_dug_format_ima_veci_budzet():
    assert zadaci.ZADACI["dubinski-clanak"].izlaz_tokena == 1600
    assert zadaci.ZADACI["objava"].izlaz_tokena is None  # podrazumevano (800)
