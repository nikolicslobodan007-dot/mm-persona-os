"""Veritas slice 1 — pokazivač-detektor i ekstraktor nalaza (bez mreže)."""

from apps.memory.veritas import nalaz, pokazivac


class TestPokazivac:
    def test_sadrzaj_sa_tvrdnjom_ide_na_analizu(self):
        t = "Ministar je juče izjavio da je budžet povećan za 12 odsto u 2026."
        r = pokazivac.analiziraj(t)
        assert r["preporuka"] == "analiziraj"
        assert r["ima_tvrdnje"] is True

    def test_link_bez_tvrdnje_prati_pokazivac(self):
        t = "Ceo snimak je na https://primer.rs/video klip broj dva tri."
        r = pokazivac.analiziraj(t)
        assert r["preporuka"] == "prati_pokazivac"
        assert any(p["vrsta"] == "url" for p in r["pokazivaci"])

    def test_fraza_bez_linka_trazi_izvor(self):
        t = "Neverovatno! Ovo moraš da vidiš! Pogledaj link u opisu odmah sada!!!"
        r = pokazivac.analiziraj(t)
        assert r["preporuka"] in ("trazi_izvor", "preskoci")

    def test_prekratko_preskoci(self):
        assert pokazivac.analiziraj("Kratko.")["preporuka"] == "preskoci"


class TestNalaz:
    def test_parsiraj_validan(self):
        sirovo = ('[{"doslovna":"A je rekao X","implicirana":"dakle Y",'
                  '"tehnika":"uokvirivanje","za_proveru":"naći izvor","pouzdanost":0.8}]')
        out = nalaz._parsiraj(sirovo, 6)
        assert len(out) == 1
        assert out[0]["tehnika"] == "uokvirivanje"
        assert out[0]["pouzdanost"] == 0.8

    def test_parsiraj_odbija_cirilicu(self):
        sirovo = '[{"doslovna":"Ово је ћирилица","tehnika":"nema","pouzdanost":0.9}]'
        assert nalaz._parsiraj(sirovo, 6) == []

    def test_nepoznata_tehnika_postaje_nema(self):
        sirovo = '[{"doslovna":"A","tehnika":"izmisljeno","pouzdanost":0.5}]'
        out = nalaz._parsiraj(sirovo, 6)
        assert out and out[0]["tehnika"] == "nema"

    def test_izvuci_nalaze_suvo(self):
        out = nalaz.izvuci_nalaze("Neki tekst sa tvrdnjom.", nalaz._lazni_llm, 6)
        assert len(out) == 1
        assert set(out[0]) == {"doslovna", "implicirana", "tehnika",
                               "za_proveru", "pouzdanost"}
