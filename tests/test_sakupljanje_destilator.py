"""Sakupljač — destilator veština + ulaz (suvi režim, bez mreže/DB)."""

from apps.memory.sakupljanje import destilator, ulaz


class TestDestilator:
    def test_suvo_daje_vestinu(self):
        r = destilator.destiluj("Neki tekst sa postupkom.", naslov="Izvor X", suvo=True)
        assert r["etiketa"] == "suvo" and r["cena"] == 0
        assert r["vestine"] and r["vestine"][0]["koraci"]

    def test_parsiraj_osnovno(self):
        s = ('[{"ime":"Rešavanje problema",'
             '"koraci":["Napravi kopiju.","Primeni izmenu."],"pouzdanost":0.8}]')
        out = destilator.parsiraj(s, "nap", 5)
        assert len(out) == 1
        assert out[0]["ime"] == "Rešavanje problema" and out[0]["napomene"] == "nap"
        assert out[0]["pouzdanost"] == 0.8

    def test_parsiraj_odbacuje_cirilicu(self):
        s = '[{"ime":"Ћирилица","koraci":["Корак један.","Корак два."],"pouzdanost":0.9}]'
        assert destilator.parsiraj(s, "nap", 5) == []

    def test_parsiraj_odbacuje_malo_koraka(self):
        s = '[{"ime":"X","koraci":["samo jedan korak"],"pouzdanost":0.9}]'
        assert destilator.parsiraj(s, "nap", 5) == []

    def test_parsiraj_odbacuje_predug_korak(self):
        dug = "a" * 400
        s = '[{"ime":"X","koraci":["kratak korak","' + dug + '"],"pouzdanost":0.9}]'
        assert destilator.parsiraj(s, "nap", 5) == []

    def test_parsiraj_prazno(self):
        assert destilator.parsiraj("nije json", "nap", 5) == []


class TestUlaz:
    def test_web_suvo(self):
        r = ulaz.procitaj("web", "https://primer.rs/clanak", suvo=True)
        assert r["vrsta"] == "web" and r["tekst"].strip()

    def test_slika_suvo(self):
        r = ulaz.procitaj("slika", "https://primer.rs/meme.png", suvo=True)
        assert r["vrsta"] == "slika" and r["tekst"].strip()

    def test_klip_suvo(self):
        r = ulaz.procitaj("klip", "https://youtu.be/x", suvo=True)
        assert r["vrsta"] == "klip" and r["tekst"].strip()

    def test_klip_fajl_suvo(self):
        r = ulaz.procitaj("klip_fajl", "/x/y.mp4", suvo=True)
        assert r["vrsta"] == "klip_fajl" and r["tekst"].strip()

    def test_nepoznata_vrsta(self):
        import pytest
        with pytest.raises(ulaz.UlazGreska):
            ulaz.procitaj("nesto", "x", suvo=True)
