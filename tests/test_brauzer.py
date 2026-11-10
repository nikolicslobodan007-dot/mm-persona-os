"""Browser Gateway (skelet) — Lightpanda pool → HTTP fallback. Bez pravog browsera."""

import pytest

from apps.memory.sakupljanje import brauzer


class TestCdpEnv:
    def test_cita_env(self, monkeypatch):
        monkeypatch.setenv("LIGHTPANDA_CDP", " ws://a:1 ")
        assert brauzer.cdp_iz_okruzenja() == "ws://a:1"

    def test_prazno_bez_env(self, monkeypatch):
        monkeypatch.delenv("LIGHTPANDA_CDP", raising=False)
        assert brauzer.cdp_iz_okruzenja() == ""


def _dozvoli(monkeypatch):
    from apps.libri import uvoz_web
    monkeypatch.setattr(uvoz_web, "proveri_bezbedan", lambda u: None)
    monkeypatch.setattr(uvoz_web, "_ua", lambda: "UA")
    monkeypatch.setattr(uvoz_web, "_robots_dozvoljava", lambda u, ua: True)


class TestRender:
    def test_lightpanda_kad_ima_pool(self, monkeypatch):
        _dozvoli(monkeypatch)
        monkeypatch.setattr(brauzer, "cdp_iz_okruzenja", lambda: "ws://x:9222")
        monkeypatch.setattr(brauzer, "_render_cdp",
                            lambda url, cdp, ua, timeout: {"html": "<b>js</b>", "naslov": "T"})
        r = brauzer.render("https://example.com")
        assert r["engine"] == "lightpanda" and r["tekst"] == "<b>js</b>"

    def test_fallback_na_http_kad_pool_padne(self, monkeypatch):
        _dozvoli(monkeypatch)
        from apps.libri import uvoz_web
        monkeypatch.setattr(brauzer, "cdp_iz_okruzenja", lambda: "ws://x:9222")

        def pukni(url, cdp, ua, timeout):
            raise RuntimeError("nema pool")

        monkeypatch.setattr(brauzer, "_render_cdp", pukni)
        monkeypatch.setattr(uvoz_web, "preuzmi", lambda u: "<html>http</html>")
        r = brauzer.render("https://example.com")
        assert r["engine"] == "http" and "http" in r["tekst"]

    def test_http_kad_nema_pool(self, monkeypatch):
        from apps.libri import uvoz_web
        monkeypatch.setattr(brauzer, "cdp_iz_okruzenja", lambda: "")
        monkeypatch.setattr(uvoz_web, "preuzmi", lambda u: "<html>plain</html>")
        r = brauzer.render("https://example.com")
        assert r["engine"] == "http" and "plain" in r["tekst"]

    def test_http_greska_je_brauzer_greska(self, monkeypatch):
        from apps.libri import uvoz_web
        monkeypatch.setattr(brauzer, "cdp_iz_okruzenja", lambda: "")
        monkeypatch.setattr(uvoz_web, "preuzmi",
                            lambda u: (_ for _ in ()).throw(uvoz_web.UvozError("pao")))
        with pytest.raises(brauzer.BrauzerGreska):
            brauzer.render("https://example.com")

    def test_suvo(self):
        assert brauzer.render("https://x", suvo=True)["engine"] == "suvo"
