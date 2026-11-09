"""Browser Gateway (skelet) — izbor engine-a, fallback, SSRF/robots. Bez pravog browsera."""

import pytest

from apps.memory.sakupljanje import brauzer


class _FakeChromium:
    def __init__(self):
        self.calls = []

    def connect_over_cdp(self, cdp):
        self.calls.append(("cdp", cdp))
        return "B"

    def launch(self, headless):
        self.calls.append(("launch", headless))
        return "B"


class _FakeP:
    def __init__(self):
        self.chromium = _FakeChromium()


class TestOtvori:
    def test_cdp_kad_je_zadat(self):
        p = _FakeP()
        assert brauzer._otvori(p, "ws://x:9222") == "B"
        assert p.chromium.calls == [("cdp", "ws://x:9222")]

    def test_launch_kad_nema_cdp(self):
        p = _FakeP()
        brauzer._otvori(p, "")
        assert p.chromium.calls == [("launch", True)]


class TestCdpEnv:
    def test_cita_env(self, monkeypatch):
        monkeypatch.setenv("LIGHTPANDA_CDP", " ws://a:1 ")
        assert brauzer.cdp_iz_okruzenja() == "ws://a:1"

    def test_prazno_bez_env(self, monkeypatch):
        monkeypatch.delenv("LIGHTPANDA_CDP", raising=False)
        assert brauzer.cdp_iz_okruzenja() == ""


def _dozvoli_mrezu(monkeypatch):
    from apps.libri import uvoz_web
    monkeypatch.setattr(uvoz_web, "proveri_bezbedan", lambda u: None)
    monkeypatch.setattr(uvoz_web, "_ua", lambda: "UA")
    monkeypatch.setattr(uvoz_web, "_robots_dozvoljava", lambda u, ua: True)


class TestRender:
    def test_lightpanda_uspeh(self, monkeypatch):
        _dozvoli_mrezu(monkeypatch)
        monkeypatch.setattr(brauzer, "cdp_iz_okruzenja", lambda: "ws://x:9222")
        monkeypatch.setattr(brauzer, "_render_jednom",
                            lambda url, cdp, ua, timeout: {"html": "h", "naslov": "t"})
        r = brauzer.render("https://example.com")
        assert r["engine"] == "lightpanda" and r["tekst"] == "h"

    def test_fallback_na_chromium(self, monkeypatch):
        _dozvoli_mrezu(monkeypatch)
        monkeypatch.setattr(brauzer, "cdp_iz_okruzenja", lambda: "ws://x:9222")
        redosled = []

        def fake(url, cdp, ua, timeout):
            redosled.append(cdp)
            if cdp:
                raise RuntimeError("nema pool")
            return {"html": "<html>ok</html>", "naslov": "T"}

        monkeypatch.setattr(brauzer, "_render_jednom", fake)
        r = brauzer.render("https://example.com")
        assert r["engine"] == "chromium" and "ok" in r["tekst"]
        assert redosled == ["ws://x:9222", ""]

    def test_robots_zabrana(self, monkeypatch):
        from apps.libri import uvoz_web
        monkeypatch.setattr(uvoz_web, "proveri_bezbedan", lambda u: None)
        monkeypatch.setattr(uvoz_web, "_ua", lambda: "UA")
        monkeypatch.setattr(uvoz_web, "_robots_dozvoljava", lambda u, ua: False)
        with pytest.raises(brauzer.BrauzerGreska):
            brauzer.render("https://example.com")

    def test_suvo_bez_mreze(self):
        r = brauzer.render("https://example.com", suvo=True)
        assert r["engine"] == "suvo"
