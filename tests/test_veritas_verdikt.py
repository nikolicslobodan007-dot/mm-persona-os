"""Veritas slice 2a — verdikt motor i sud o izvoru (bez mreže/DB)."""

from apps.memory.veritas import sud, verdikt


class TestVerdikt:
    def _izvor(self, vrsta, stav, i=0):
        return {"vrsta": vrsta, "stav": stav, "id": f"{vrsta}-{i}"}

    def test_svedok_sam_je_verovatno(self):
        r = verdikt.oceni_tvrdnju("T", [self._izvor("svedok", verdikt.POTVRDJUJE)])
        assert r["verdikt"] == "VEROVATNO"
        assert r["ose"]["blizina"] == 0.9

    def test_svedok_i_dve_redakcije_potvrdjeno(self):
        izvori = [self._izvor("svedok", verdikt.POTVRDJUJE),
                  self._izvor("redakcija", verdikt.POTVRDJUJE, 1),
                  self._izvor("redakcija", verdikt.POTVRDJUJE, 2)]
        r = verdikt.oceni_tvrdnju("T", izvori)
        assert r["verdikt"] == "POTVRĐENO"
        assert r["ose"]["ukupno"] >= 0.9

    def test_protivrecan_izvor_daje_delimicno(self):
        izvori = [self._izvor("svedok", verdikt.POTVRDJUJE),
                  self._izvor("web", verdikt.OPONIRA, 1)]
        r = verdikt.oceni_tvrdnju("T", izvori)
        assert r["verdikt"] == "DELIMIČNO"
        assert r["protivrecnih"] == 1

    def test_sam_tabloid_nedovoljno(self):
        r = verdikt.oceni_tvrdnju("T", [self._izvor("tabloid", verdikt.POTVRDJUJE)])
        assert r["verdikt"] == "NEDOVOLJNO"


    def test_sporno_tumacenje_i_dalje_potvrdjuje_izreceno(self):
        # „izvučeno iz konteksta" potvrđuje da je izrečeno, spori značenje
        izvori = [self._izvor("svedok", verdikt.POTVRDJUJE),
                  self._izvor("redakcija", verdikt.POTVRDJUJE, 1),
                  self._izvor("redakcija", verdikt.SPORNO, 2)]
        r = verdikt.oceni_tvrdnju("T", izvori)
        assert r["verdikt"] == "POTVRĐENO"
        assert r["protivrecnih"] == 0
        assert r["sporno_tumacenje"] == 1

    def test_bez_izvora_nedovoljno(self):
        r = verdikt.oceni_tvrdnju("T", [])
        assert r["verdikt"] == "NEDOVOLJNO"
        assert r["izvori"] == 0


class TestSud:
    def test_parsiraj_validan(self):
        out = sud._parsiraj('{"stav":"oponira","obrazlozenje":"Izvor tvrdi suprotno."}')
        assert out["stav"] == "oponira"

    def test_parsiraj_nepoznat_stav(self):
        assert sud._parsiraj('{"stav":"mozda"}') is None

    def test_oceni_izvor_suvo(self):
        out = sud.oceni_izvor("T", "neki tekst", sud._lazni_llm)
        assert out["stav"] == "potvrdjuje"
