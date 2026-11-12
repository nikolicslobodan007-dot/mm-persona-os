"""ADR-0147 — dug sadržaj ide i kao PDF na Telegram (sendDocument)."""

from __future__ import annotations

from types import SimpleNamespace


class _Resp:
    def read(self):
        return b'{"ok":true}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_posalji_dokument_gradi_multipart(monkeypatch):
    from apps.channels import telegram
    monkeypatch.setattr(telegram, "_token", lambda: "T0KEN")
    uhvaceno = {}

    def _urlopen(req, timeout=0):
        uhvaceno["url"] = req.full_url
        uhvaceno["data"] = req.data
        return _Resp()

    monkeypatch.setattr(telegram.urllib.request, "urlopen", _urlopen)
    telegram.posalji_dokument(555, b"%PDF-1.4 proba", "analiza.pdf", "opis")
    assert "sendDocument" in uhvaceno["url"]
    assert b'name="chat_id"' in uhvaceno["data"] and b"555" in uhvaceno["data"]
    assert b'filename="analiza.pdf"' in uhvaceno["data"]
    assert b"%PDF-1.4 proba" in uhvaceno["data"]


def test_posalji_dokument_bez_tokena_ne_salje(monkeypatch):
    from apps.channels import telegram
    monkeypatch.setattr(telegram, "_token", lambda: "")
    pozvan = {"n": 0}
    monkeypatch.setattr(telegram.urllib.request, "urlopen",
                        lambda *a, **k: pozvan.__setitem__("n", 1))
    telegram.posalji_dokument(1, b"x", "a.pdf")
    assert pozvan["n"] == 0


def test_mozda_dokument_bez_itema_nista(monkeypatch):
    from apps.channels import tasks, telegram
    poslato = {"n": 0}
    monkeypatch.setattr(telegram, "posalji_dokument",
                        lambda *a, **k: poslato.__setitem__("n", 1))
    tasks._mozda_dokument(123, SimpleNamespace(delovi={}))
    assert poslato["n"] == 0


def test_mozda_dokument_kratak_format_ne_ide(monkeypatch):
    from apps.channels import tasks, telegram
    from apps.content.models import ContentItem
    poslato = {"n": 0}
    monkeypatch.setattr(
        ContentItem.objects, "filter",
        lambda **kw: SimpleNamespace(
            first=lambda: SimpleNamespace(format="post", title="x")))
    monkeypatch.setattr(telegram, "posalji_dokument",
                        lambda *a, **k: poslato.__setitem__("n", 1))
    tasks._mozda_dokument(123, SimpleNamespace(delovi={"item": "abc"}))
    assert poslato["n"] == 0  # objava (post) ne ide kao PDF
