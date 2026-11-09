"""Sakupljanje ulaz — GitHub repo se čita kao pun README (raw), ne HTML landing."""

from apps.memory.sakupljanje import ulaz


class TestGithubRepo:
    def test_repo_koren(self):
        assert ulaz._github_repo("https://github.com/janestreet/agent_skills") == \
            ("janestreet", "agent_skills")

    def test_tree_grana(self):
        assert ulaz._github_repo("https://github.com/owner/repo/tree/main") == \
            ("owner", "repo")

    def test_git_sufiks(self):
        assert ulaz._github_repo("https://github.com/owner/repo.git") == ("owner", "repo")

    def test_profil_bez_repoa(self):
        assert ulaz._github_repo("https://github.com/owner") is None

    def test_rezervisan_owner(self):
        assert ulaz._github_repo("https://github.com/features/copilot") is None

    def test_nije_github(self):
        assert ulaz._github_repo("https://gitlab.com/owner/repo") is None


class TestWebGithub:
    def test_readme_se_koristi(self, monkeypatch):
        pun = "# Agent skills\n" + ("Bogat sadržaj README-a. " * 50)
        monkeypatch.setattr(ulaz, "_github_readme", lambda o, r: pun)
        izvor = ulaz._web("https://github.com/janestreet/agent_skills", False)
        assert izvor["tekst"] == pun
        assert "README" in izvor["naslov"]
        assert izvor["izvor"] == "https://github.com/janestreet/agent_skills"

    def test_fallback_na_html_kad_nema_readme(self, monkeypatch):
        monkeypatch.setattr(ulaz, "_github_readme", lambda o, r: "")
        from apps.libri import uvoz_web
        monkeypatch.setattr(uvoz_web, "preuzmi",
                            lambda u: "<title>Repo</title><p>HTML telo stranice.</p>")
        izvor = ulaz._web("https://github.com/owner/repo", False)
        assert "HTML telo" in izvor["tekst"]

    def test_suvo_ne_dira_mrezu(self):
        izvor = ulaz._web("https://github.com/owner/repo", True)
        assert "rezervnu kopiju" in izvor["tekst"]
