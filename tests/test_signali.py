"""GitHub Signals izvor — nabrajanje kandidata (bez mreže/LLM)."""

from io import StringIO

from django.core.management import call_command

from apps.memory.management.commands import signali

_CSV = (
    "published_at,provider,post_url,repo_slug,repo_url,repo_stars,"
    "repo_keywords,caption,likes,plays,comments\n"
    "2026-11-01,telegram,https://t.me/x/1,a/alpha,https://github.com/a/alpha,"
    '78,"music,android",promo,,,\n'
    "2026-11-01,youtube,https://www.youtube.com/watch?v=ZZ,b/beta,"
    "https://github.com/b/beta,53,,cap,,,\n"
    "2026-11-01,telegram,https://t.me/x/2,c/gamma,https://github.com/c/gamma,"
    "5,,low,,,\n"
    "2026-11-01,telegram,https://t.me/x/3,a/alpha,https://github.com/a/alpha,"
    "78,,dup,,,\n"
)


class TestParsiraj:
    def test_bitne_kolone(self):
        redovi = signali._parsiraj(_CSV)
        assert len(redovi) == 4
        r = redovi[0]
        assert r["slug"] == "a/alpha"
        assert r["repo_url"] == "https://github.com/a/alpha"
        assert r["zvezdica"] == 78
        assert r["provajder"] == "telegram"

    def test_preskace_bez_slug_ili_url(self):
        tekst = ("repo_slug,repo_url,repo_stars\n"
                 ",https://github.com/x/y,10\n"
                 "x/y,,10\n")
        assert signali._parsiraj(tekst) == []


class TestFiltriraj:
    def test_prag_dedup_sort(self):
        kandidati = signali._filtriraj(signali._parsiraj(_CSV), 20)
        assert [r["slug"] for r in kandidati] == ["a/alpha", "b/beta"]

    def test_prag_odbacuje_sve(self):
        assert signali._filtriraj(signali._parsiraj(_CSV), 1000) == []


class TestKomande:
    def test_youtube_daje_url_i_klip(self):
        r = {"repo_url": "https://github.com/b/beta", "provajder": "youtube",
             "post_url": "https://www.youtube.com/watch?v=ZZ"}
        kom = signali._komande(r)
        assert any("--url" in k for k in kom)
        assert any("--klip-url" in k for k in kom)

    def test_telegram_samo_url(self):
        r = {"repo_url": "https://github.com/a/alpha", "provajder": "telegram",
             "post_url": "https://t.me/x/1"}
        kom = signali._komande(r)
        assert len(kom) == 1 and "--url" in kom[0]


class TestKomanda:
    def test_lista_ispisuje(self, tmp_path):
        p = tmp_path / "export.csv"
        p.write_text(_CSV, encoding="utf-8")
        out = StringIO()
        call_command("signali", "--lista", "--csv-fajl", str(p),
                     "--min-zvezdica", "20", stdout=out)
        s = out.getvalue()
        assert "a/alpha" in s and "b/beta" in s
        assert "c/gamma" not in s
