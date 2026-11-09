"""Sakupljač — pokazivač pre-filter u `sakupi` (bez mreže/DB)."""

from io import StringIO

from django.core.management import call_command

from apps.memory.sakupljanje import ulaz
from apps.memory.veritas import pokazivac


class TestPokazivacOdluka:
    def test_pravi_postupak_analiziraj(self):
        t = "Prvo napravi kopiju. Zatim primeni izmenu. Na kraju proveri rezultat."
        assert pokazivac.analiziraj(t)["preporuka"] == "analiziraj"

    def test_link_bez_sadrzaja_prati(self):
        t = "Ceo tutorijal je na https://github.com/owner/repo"
        o = pokazivac.analiziraj(t)
        assert o["preporuka"] == "prati_pokazivac"
        assert any(p["vrsta"] in ("url", "github", "www") for p in o["pokazivaci"])

    def test_fraza_bez_linka_trazi(self):
        t = "Subscribe for more and check the link in bio for the full video today"
        assert pokazivac.analiziraj(t)["preporuka"] == "trazi_izvor"

    def test_prazno_preskoci(self):
        assert pokazivac.analiziraj("ok")["preporuka"] == "preskoci"


def _fake_izvor(tekst):
    def _f(vrsta, vrednost, *, suvo=False):
        return {"tekst": tekst, "naslov": vrednost, "izvor": vrednost, "vrsta": "web"}
    return _f


class TestSakupiPrefilter:
    def test_preskace_reklamu(self, monkeypatch):
        monkeypatch.setattr(
            ulaz, "procitaj",
            _fake_izvor("Subscribe for more! Link in bio for the full video."))
        out = StringIO()
        call_command("sakupi", "--url", "https://promo.example", "--suvo", stdout=out)
        s = out.getvalue()
        assert "preskač" in s.lower()
        assert "veština (" not in s

    def test_destiluje_pravi_postupak(self, monkeypatch):
        monkeypatch.setattr(
            ulaz, "procitaj",
            _fake_izvor("Prvo napravi kopiju. Zatim primeni izmenu. Na kraju proveri."))
        out = StringIO()
        call_command("sakupi", "--url", "https://x.example", "--suvo", stdout=out)
        s = out.getvalue()
        assert "analiziraj" in s
        assert "veština (" in s

    def test_bez_filtera_ne_preskace(self, monkeypatch):
        monkeypatch.setattr(
            ulaz, "procitaj",
            _fake_izvor("Subscribe for more! Link in bio."))
        out = StringIO()
        call_command("sakupi", "--url", "https://promo.example", "--suvo",
                     "--bez-filtera", stdout=out)
        s = out.getvalue()
        assert "preskač" not in s.lower()
        assert "veština (" in s

    def test_prati_pokazivac(self, monkeypatch):
        def _f(vrsta, vrednost, *, suvo=False):
            if "github" in vrednost:
                t = "Prvo kloniraj repo. Zatim pokreni skriptu. Na kraju proveri izlaz."
            else:
                t = "Ceo tutorijal na https://github.com/owner/repo"
            return {"tekst": t, "naslov": vrednost, "izvor": vrednost, "vrsta": "web"}
        monkeypatch.setattr(ulaz, "procitaj", _f)
        out = StringIO()
        call_command("sakupi", "--url", "https://x.example", "--suvo", stdout=out)
        s = out.getvalue()
        assert "pratim pokazivač" in s
        assert "veština (" in s
