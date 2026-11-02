"""Veritas slice 2b — Brave pretraga (parsiranje, bez mreže)."""

from apps.memory.veritas import pretraga


class TestPretraga:
    def test_parsiraj_izvlaci_http_url(self):
        data = {"web": {"results": [
            {"url": "https://a.rs/1", "title": "A"},
            {"url": "https://b.rs/2", "title": "B"},
            {"url": "ftp://x", "title": "X"}]}}
        out = pretraga._parsiraj(data, 5)
        assert [r["url"] for r in out] == ["https://a.rs/1", "https://b.rs/2"]

    def test_parsiraj_dedup_i_maks(self):
        data = {"web": {"results": [
            {"url": "https://a.rs/1"}, {"url": "https://a.rs/1"}, {"url": "https://c.rs/3"}]}}
        assert len(pretraga._parsiraj(data, 1)) == 1

    def test_parsiraj_prazno(self):
        assert pretraga._parsiraj({}, 5) == []

    def test_lazni_vraca_url_listu(self):
        out = pretraga._lazni("neki upit", 5)
        assert out and all(r["url"].startswith("http") for r in out)
