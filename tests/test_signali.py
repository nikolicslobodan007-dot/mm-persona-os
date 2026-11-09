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


class TestPutanjaIObrada:
    def test_putanja(self):
        assert signali._putanja("/d", "a/alpha") == "/d/a__alpha.json"

    def test_za_obradu_preskace_postojece_i_kapira(self, tmp_path):
        (tmp_path / "a__alpha.json").write_text("[]", encoding="utf-8")
        kandidati = [
            {"slug": "a/alpha", "repo_url": "u1", "zvezdica": 9},
            {"slug": "b/beta", "repo_url": "u2", "zvezdica": 8},
            {"slug": "c/gamma", "repo_url": "u3", "zvezdica": 7},
        ]
        zo = signali._za_obradu(kandidati, str(tmp_path), 2)
        assert [r["slug"] for r, _ in zo] == ["b/beta", "c/gamma"]

    def test_za_obradu_kapira_na_najvise(self, tmp_path):
        kandidati = [{"slug": f"o/r{i}", "repo_url": "u", "zvezdica": 1} for i in range(5)]
        assert len(signali._za_obradu(kandidati, str(tmp_path), 1)) == 1

    def test_za_obradu_preskace_vec_uvezene(self, tmp_path):
        kandidati = [
            {"slug": "a/alpha", "repo_url": "u", "zvezdica": 9},
            {"slug": "b/beta", "repo_url": "u", "zvezdica": 8},
        ]
        zo = signali._za_obradu(kandidati, str(tmp_path), 5, uvezeni={"a/alpha"})
        assert [r["slug"] for r, _ in zo] == ["b/beta"]


class TestSakupiGate:
    def test_bez_najvise_pada(self):
        import pytest
        from django.core.management.base import CommandError
        with pytest.raises(CommandError):
            call_command("signali", "--sakupi")


class TestLicenca:
    def test_spdx_u_kutiju(self):
        assert signali._spdx_u_kutiju("MIT") == ("SLOBODNA", "MIT")
        assert signali._spdx_u_kutiju("Apache-2.0") == ("SLOBODNA", "Apache-2.0")
        assert signali._spdx_u_kutiju("GPL-3.0") == ("ZARAZNA", "")
        assert signali._spdx_u_kutiju("MPL-2.0") == ("ZARAZNA", "")
        assert signali._spdx_u_kutiju("CC-BY-NC-4.0") == ("ZABRANJENA", "")
        assert signali._spdx_u_kutiju("NOASSERTION") == ("NEPOZNATA", "")
        assert signali._spdx_u_kutiju("") == ("NEPOZNATA", "")

    def test_vestina_komanda(self):
        k = signali._vestina_komanda("p.json", "GitHub Signals: o/r",
                                     "https://github.com/o/r", "SLOBODNA", "MIT")
        assert "--licenca SLOBODNA" in k
        assert '--naziv-licence "MIT"' in k
        assert "--actor user:slobodan" in k

    def test_vestina_komanda_bez_naziva(self):
        k = signali._vestina_komanda("p", "i", "u", "NEPOZNATA", "")
        assert "--licenca NEPOZNATA" in k and "--naziv-licence" not in k

    def test_licence_emituje_komande(self, tmp_path, monkeypatch):
        (tmp_path / "janestreet__agent_skills.json").write_text("[]", encoding="utf-8")
        monkeypatch.setattr(signali, "_github_licenca", lambda o, r: "MIT")
        out = StringIO()
        call_command("signali", "--licence", "--izlaz-dir", str(tmp_path), stdout=out)
        s = out.getvalue()
        assert "janestreet/agent_skills" in s
        assert "SLOBODNA" in s
        assert "manage.py vestina" in s
        assert "--actor user:slobodan" in s

    def test_licence_skripta(self, tmp_path, monkeypatch):
        (tmp_path / "o__r.json").write_text("[]", encoding="utf-8")
        monkeypatch.setattr(signali, "_github_licenca", lambda o, r: "MIT")
        skripta = tmp_path / "uvoz.sh"
        call_command("signali", "--licence", "--izlaz-dir", str(tmp_path),
                     "--skripta", str(skripta), stdout=StringIO())
        tekst = skripta.read_text(encoding="utf-8")
        assert tekst.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in tekst
        assert "manage.py vestina" in tekst
        assert "--actor user:slobodan" in tekst
