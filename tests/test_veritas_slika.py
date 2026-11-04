"""Veritas slice 3.1 — OCR slika + zajednički izlaz (suvi režim, bez mreže/DB)."""

import pytest

from apps.memory.veritas import izlaz, slika


class _Stil:
    def __getattr__(self, _name):
        return lambda s="": s


class _Out:
    def __init__(self):
        self.red = []

    def write(self, s=""):
        self.red.append(s)


class _Cmd:
    def __init__(self):
        self.stdout = _Out()
        self.style = _Stil()


class TestSlika:
    def test_procitaj_suvo(self):
        rez = slika.procitaj("https://primer.rs/meme.png", suvo=True)
        assert rez["asset_id"] is None
        assert rez["tekst"].strip()
        assert rez["izvor_url"].startswith("http")

    def test_lose_url_pada(self):
        with pytest.raises(slika.SlikaGreska):
            slika._skini("ftp://x/y")


class TestIzlaz:
    def test_prazan_tekst(self):
        cmd = _Cmd()
        izlaz.prikazi_nalaze(cmd, "   ", {"suvo": True, "maks_nalaza": 6, "proveri": False})
        assert any("Prazan" in r for r in cmd.stdout.red)

    def test_nalazi_bez_provere(self):
        cmd = _Cmd()
        izlaz.prikazi_nalaze(cmd, "U tekstu se iznosi tvrdnja.",
                             {"suvo": True, "maks_nalaza": 6, "proveri": False})
        spojeno = "\n".join(cmd.stdout.red)
        assert "nalaz(a)" in spojeno and "doslovno" in spojeno
        assert "Provera" not in spojeno

    def test_nalazi_sa_proverom(self):
        cmd = _Cmd()
        izlaz.prikazi_nalaze(cmd, "Neki tekst za proveru.",
                             {"suvo": True, "maks_nalaza": 6, "proveri": True,
                              "maks_tvrdnji": 1, "maks_izvora": 2})
        spojeno = "\n".join(cmd.stdout.red)
        assert "Provera" in spojeno and "VERDIKT" in spojeno
