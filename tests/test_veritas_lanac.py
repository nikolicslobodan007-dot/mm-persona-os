"""Veritas slice 4 — lanac tvrdnja → verdikt (suvi režim, bez mreže/DB)."""

from apps.memory.veritas import lanac, sud


class TestLanac:
    def test_suvo_pretraga_daje_izvore_i_verdikt(self):
        rez = lanac.proveri_tvrdnju(
            "Ministar je izjavio nešto sporno", llm=sud._lazni_llm,
            maks_izvora=4, suvo=True, pretrazi=True)
        assert len(rez["kandidati"]) == 3          # _lazni vraća min(maks,3)
        v = rez["verdikt"]
        assert v["izvori"] == 3 and v["saglasnih"] == 3 and v["protivrecnih"] == 0
        assert set(("verdikt", "ose", "izvori", "sporno_tumacenje")) <= set(v)

    def test_svedok_bez_pretrage(self):
        rez = lanac.proveri_tvrdnju(
            "To sam gledao uživo", llm=sud._lazni_llm, suvo=True, pretrazi=False,
            svedoci=[{"vrsta": "svedok", "opis": "gledao uživo na TV"}])
        assert rez["kandidati"] == []
        assert rez["verdikt"]["izvori"] == 1       # samo svedok

    def test_na_dogadjaj_pozvan(self):
        dogadjaji = []
        lanac.proveri_tvrdnju(
            "Neka tvrdnja", llm=sud._lazni_llm, maks_izvora=2, suvo=True,
            pretrazi=True, na_dogadjaj=lambda t, d: dogadjaji.append(t))
        assert "pretraga" in dogadjaji
        assert dogadjaji.count("izvor") == 2       # min(2,3)=2 izvora
