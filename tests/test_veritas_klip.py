"""Veritas slice 3 — klip → transkript (bez mreže, bez DB-a).

Pokriva: suvi režim klipa, Groq ugovor u `_call_external_audio` (preko fakeova),
i da `_post_multipart` sastavi ispravan multipart zahtev.
"""

import types

from apps.memory.veritas import klip


class TestKlipSuvo:
    def test_transkribuj_suvo_vraca_tekst(self):
        rez = klip.transkribuj("https://primer.rs/klip", suvo=True)
        assert rez["provider"] == "suvo"
        assert rez["transkript"].strip()
        assert rez["cena_centi"] == 0

    def test_lose_url_pada(self):
        import pytest
        with pytest.raises(klip.KlipGreska):
            klip._skini_audio("ftp://x/y", "/tmp")


class TestGroqUgovor:
    def test_call_external_audio_vraca_tekst_i_sekunde(self, monkeypatch):
        from apps.llm_gateway import gateway
        from apps.visuals import storage

        monkeypatch.setenv("GROQ_API_KEY", "test-kljuc")
        monkeypatch.setattr(storage, "get", lambda key: b"FAKEAUDIO")

        poslato = {}

        def fake_multipart(url, headers, fields, files, timeout):
            poslato["url"] = url
            poslato["fields"] = fields
            poslato["auth"] = headers.get("Authorization")
            return {"text": "zdravo svete"}

        monkeypatch.setattr(gateway, "_post_multipart", fake_multipart)

        route = types.SimpleNamespace(
            provider="groq", is_openai_compatible=True,
            base_url="https://api.groq.com/openai/v1",
            model_key="whisper-large-v3-turbo", quota_json={"language": "sr"},
            timeout_seconds=120)
        asset = types.SimpleNamespace(
            storage_key="veritas/klip/abc.mp3", mime_type="audio/mpeg", duration_ms=12000)

        tekst, tin, tout, finish = gateway._call_external_audio(route, asset)
        assert tekst == "zdravo svete"
        assert tin == 12 and tout == 0 and finish == "stop"
        assert poslato["url"].endswith("/audio/transcriptions")
        assert poslato["fields"]["model"] == "whisper-large-v3-turbo"
        assert poslato["fields"]["language"] == "sr"
        assert poslato["auth"] == "Bearer test-kljuc"


class TestPostMultipart:
    def test_sastavlja_multipart_zahtev(self, monkeypatch):
        from apps.llm_gateway import gateway

        uhvaceno = {}

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"text":"ok"}'

        def fake_urlopen(req, timeout=None):
            uhvaceno["ctype"] = req.headers.get("Content-type")
            uhvaceno["telo"] = req.data
            return FakeResp()

        monkeypatch.setattr(gateway.urllib.request, "urlopen", fake_urlopen)
        out = gateway._post_multipart(
            "https://x/api", {"Authorization": "Bearer k"},
            {"model": "m"}, {"file": ("a.mp3", b"BYTES", "audio/mpeg")}, 30)
        assert out == {"text": "ok"}
        assert "multipart/form-data; boundary=" in uhvaceno["ctype"]
        assert b'name="model"' in uhvaceno["telo"]
        assert b'filename="a.mp3"' in uhvaceno["telo"]
        assert b"BYTES" in uhvaceno["telo"]


class TestCookies:
    def test_bez_fajla_prazno(self, monkeypatch, tmp_path):
        from apps.memory.veritas import klip
        monkeypatch.setenv("YT_COOKIES_FILE", str(tmp_path / "nema.txt"))
        assert klip._cookies_args() == []

    def test_sa_fajlom(self, monkeypatch, tmp_path):
        from apps.memory.veritas import klip
        f = tmp_path / "c.txt"
        f.write_text("cookie")
        monkeypatch.setenv("YT_COOKIES_FILE", str(f))
        assert klip._cookies_args() == ["--cookies", str(f)]


class TestFajl:
    def test_je_fajl_nema_fajla(self):
        import pytest
        from apps.memory.veritas import klip
        with pytest.raises(klip.KlipGreska):
            klip.transkribuj("/ne/postoji/x.mp4", je_fajl=True)
