"""Poslušnik — ono malo logike koju ima. ADR-0038, ADR-0039.

Poslušnik je 25.09. satima ćutao jer je čitao `tasks` sa vrha odgovora, a Canon
§8.1 ga stavlja pod `data`. Nije pao, nije se požalio — samo je vraćao prazan red.
Nije bilo nijednog testa nad njegovim kodom, pa se to videlo tek na serveru.

Ovi testovi ne mogu da provere okruženje (kontejneri, mreža, Docker), ali mogu
tri stvari koje su čista logika: raspakivanje odgovora, oblik `task_id` i to da
zaglavlja nose ono što Canon §8.5 traži.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parent.parent / "deploy/runner/runner.py"


def _ucitaj():
    spec = importlib.util.spec_from_file_location("runner_pod_testom", RUNNER)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture(scope="module")
def runner():
    return _ucitaj()


class TestOmotac:
    """Canon §8.1 — svaki odgovor je `{"data": …, "meta": …}`."""

    def test_vadi_data(self, runner):
        odgovor = {"data": {"tasks": ["TSK-01M3C15CJ999KE2FX8PG6KHMZE"]},
                   "meta": {"request_id": "r", "schema_version": "1.0"}}
        assert runner.raspakuj(odgovor)["tasks"] == [
            "TSK-01M3C15CJ999KE2FX8PG6KHMZE"]

    def test_bez_omotaca_prolazi_kakav_jeste(self, runner):
        assert runner.raspakuj({"tasks": []}) == {"tasks": []}

    @pytest.mark.parametrize("smece", [None, [], "tekst", 7])
    def test_smece_daje_prazan_recnik(self, runner, smece):
        assert runner.raspakuj(smece) == {}

    def test_prazan_red_nije_greska(self, runner):
        assert runner.raspakuj({"data": {"tasks": []}}).get("tasks", []) == []

    def test_data_koji_nije_recnik(self, runner):
        """`data` ume da bude lista — tada se ne pretvaramo da je nema."""
        odgovor = {"data": [1, 2], "meta": {}}
        assert runner.raspakuj(odgovor) == odgovor


class TestIdentifikator:
    """`task_id` je jedino što ulazi spolja (ADR-0038 §2)."""

    def test_ispravan(self, runner):
        assert runner.TSK.match("TSK-01M3C15CJ999KE2FX8PG6KHMZE")

    @pytest.mark.parametrize("los", [
        "TSK-kratko", "PLN-01M3C15CJ999KE2FX8PG6KHMZE", "",
        "TSK-01M3C15CJ999KE2FX8PG6KHMZE; rm -rf /",
        "../../etc/passwd", "TSK-01M3C15CJ999KE2FX8PG6KHMZEX",
        "tsk-01m3c15cj999ke2fx8pg6khmze",
    ])
    def test_odbijen(self, runner, los):
        assert not runner.TSK.match(los)


class TestZaglavlja:
    """Canon §8.5 — bez ovoga svaki POST vraća 400."""

    def test_nosi_sve_sto_canon_trazi(self, runner):
        h = runner.zaglavlja()
        assert set(h) >= {"Authorization", "Content-Type", "X-Request-ID",
                          "traceparent", "X-Actor-ID"}
        assert h["X-Actor-ID"] == "service:runner"

    def test_traceparent_je_w3c_oblika(self, runner):
        import re
        assert re.match(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$",
                        runner.zaglavlja()["traceparent"])

    def test_svaki_zahtev_ima_svoj_trag(self, runner):
        prvi, drugi = runner.zaglavlja(), runner.zaglavlja()
        assert prvi["traceparent"] != drugi["traceparent"]
        assert prvi["X-Request-ID"] != drugi["X-Request-ID"]


class TestGrana:
    """ADR-0043 — oblik onoga što poslušnik dobije pre nego što napravi commit.

    Ime grane i potpis autora prave se u aplikaciji, ali ih poslušnik ipak
    proverava. Razlog je isti kao kod `task_id`: kad bi prelom reda ili `<`
    prošli kroz potpis, agentov naslov bi birao ime autora commita.
    """

    def test_ispravna_grana(self, runner):
        assert runner.GRANA.match("zadatak/TSK-01M3C15CJ999KE2FX8PG6KHMZE")

    @pytest.mark.parametrize("losa", [
        "main",
        "zadatak/TSK-01M3C15CJ999KE2FX8PG6KHMZ",      # kratak
        "zadatak/TSK-01M3C15CJ999KE2FX8PG6KHMZEE",    # dug
        "zadatak/TSK-01M3C15CJ999KE2FX8PG6KHMZI",     # I nije u Crockford base32
        "zadatak/TSK-01M3C15CJ999KE2FX8PG6KHMZE/../main",
        "../main",
        "",
    ])
    def test_odbijena_grana(self, runner, losa):
        assert not runner.GRANA.match(losa)

    def test_ispravan_potpis(self, runner):
        assert runner.POTPIS.match("Lazar Todorović (AI) <p-00027@agenti.example.com>")

    @pytest.mark.parametrize("los", [
        "Zli <root@host> <p-1@x.com>",
        "Prvi red\nSubject: lažni <p-1@x.com>",
        "Bez adrese",
        "<p-1@x.com>",
        "",
    ])
    def test_odbijen_potpis(self, runner, los):
        assert not runner.POTPIS.match(los)

    def test_sha_je_cetrdeset_malih_cifara(self, runner):
        assert runner.SHA.match("a" * 40)
        assert not runner.SHA.match("A" * 40)
        assert not runner.SHA.match("a" * 39)


class TestNeuspehBezLazneKapije:
    """ADR-0049 — greška pre kapija se prijavljuje kao neprimenjena zakrpa.

    27.09. je zakrpa pala na `apply --check: corrupt patch at line 22`, a poslušnik
    je upisao `pytest: False` — jedini način koji je imao da posao izađe iz reda
    (ADR-0040). U `ucinak`-u je tako stajao pali test koji nije pokrenut. Test koji
    nije pokrenut se ne upisuje kao pao.
    """

    TASK = "TSK-01M3C15CJ999KE2FX8PG6KHMZE"
    RAD = {
        "diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n",
        "base_sha": "b" * 40,
        "patch_id": "3f1c9f2a-0000-4000-8000-000000000001",
        "branch": f"zadatak/{TASK}",
        "branch_expected_sha": "",
        "author_name": "Lazar Todorović (AI)",
        "author_email": "p-00027@agenti.example.com",
        "commit_message": "zadatak: proba\n",
    }

    @pytest.fixture
    def zvao(self, runner, monkeypatch):
        """Beleži svaki poziv API-ja, bez mreže."""
        pozivi: list[tuple[str, dict | None]] = []

        def lazni_api(putanja, telo=None):
            pozivi.append((putanja, telo))
            return self.RAD if putanja.endswith("/work") else {}

        monkeypatch.setattr(runner, "api", lazni_api)
        monkeypatch.setattr(runner, "radni_primerak", lambda *a, **k: None)
        monkeypatch.setattr(runner, "zapamti", lambda *a, **k: "c" * 40)
        monkeypatch.setattr(runner, "gurni", lambda *a, **k: None)
        monkeypatch.setattr(runner, "primeni", lambda *a, **k: None)
        monkeypatch.setattr(runner, "kapije", lambda *a, **k: (True, {"pytest": True}))
        return pozivi

    def _putanje(self, pozivi):
        return [p for p, _ in pozivi]

    def test_neprimenjiva_zakrpa_ne_daje_kapiju(self, runner, monkeypatch, zvao):
        def pukni(*a, **k):
            raise RuntimeError("apply --check: corrupt patch at line 22")

        monkeypatch.setattr(runner, "primeni", pukni)
        runner.obradi(self.TASK)
        putanje = self._putanje(zvao)
        assert not any(p.endswith("/gate") for p in putanje), putanje
        assert any(p.endswith("/unapplied") for p in putanje), putanje
        telo = next(t for p, t in zvao if p.endswith("/unapplied"))
        assert telo["patch"] == self.RAD["patch_id"]
        assert "corrupt patch at line 22" in telo["reason"]

    def test_neuspeh_posle_kapija_ne_prijavljuje_neprimenjivost(
            self, runner, monkeypatch, zvao):
        """Kapije su izmerene i ostaju; `push` koji posle padne nije stvar zakrpe."""
        def pukni(*a, **k):
            raise RuntimeError("force-with-lease odbijen")

        monkeypatch.setattr(runner, "gurni", pukni)
        runner.obradi(self.TASK)
        putanje = self._putanje(zvao)
        assert any(p.endswith("/gate") for p in putanje), putanje
        assert not any(p.endswith("/unapplied") for p in putanje), putanje

    def test_uspesan_prolaz_ne_diras(self, runner, zvao):
        runner.obradi(self.TASK)
        putanje = self._putanje(zvao)
        assert any(p.endswith("/gate") for p in putanje)
        assert any(p.endswith("/result") for p in putanje)
        assert not any(p.endswith("/unapplied") for p in putanje)

    def test_bez_identifikatora_zakrpe_se_ne_prijavljuje_nista(
            self, runner, monkeypatch, zvao):
        """Bez `patch_id` nema šta da se odbije — greška ostaje samo u dnevniku."""
        rad = dict(self.RAD, patch_id="")
        monkeypatch.setattr(runner, "api",
                            lambda p, t=None: (zvao.append((p, t)) or
                                               (rad if p.endswith("/work") else {})))

        def pukni(*a, **k):
            raise RuntimeError("nema mesta na disku")

        monkeypatch.setattr(runner, "primeni", pukni)
        runner.obradi(self.TASK)
        assert not any(p.endswith("/unapplied") for p in self._putanje(zvao))

    def test_petlja_prezivljava_pao_zadatak(self, runner, monkeypatch, zvao):
        """`GET /work` stoji pre `try` u `obradi`; petlja mora da ga preživi.

        Bez ovoga je jedan neuspeo poziv gasio ceo proces, a red je posle ćutao —
        isto ponašanje kao 25.09., samo iz drugog razloga.
        """
        def pukni(*a, **k):
            raise RuntimeError("API nedostupan")

        monkeypatch.setattr(runner, "api", pukni)
        with pytest.raises(RuntimeError):
            runner.obradi(self.TASK)      # `obradi` sam ovo ne hvata

        red = {"tasks": [self.TASK]}
        koraci = []

        def api_koji_pada_na_radu(putanja, telo=None):
            koraci.append(putanja)
            if putanja.endswith("/queued"):
                return red
            raise RuntimeError("API nedostupan")

        monkeypatch.setattr(runner, "api", api_koji_pada_na_radu)
        monkeypatch.setattr(runner, "TOKEN", "t")
        monkeypatch.setattr(runner, "PAUZA", 0)

        def stani(_):
            raise KeyboardInterrupt

        monkeypatch.setattr(runner.time, "sleep", stani)
        with pytest.raises(KeyboardInterrupt):
            runner.main()                 # do `sleep` se stiglo → pad je uhvaćen
        assert any(p.endswith("/work") for p in koraci), koraci


class TestRadniKoren:
    """ADR-0057 — radni primerak mora da stoji tamo gde ga i Docker vidi.

    Primerak se u kontejner ubacuje bind montiranjem **po putanji**, a demon je
    razrešava u svom prostoru imena. Pod `systemd`-om sa `PrivateTmp=true` to
    nije isti direktorijum: demon montira prazan, kapije padnu na „nema
    kapije.sh", i u zapisu stoji da je agent oborio kapije.
    """

    def _main(self, runner, monkeypatch, tmp_path, *, moze, vidi):
        monkeypatch.setattr(runner, "TOKEN", "t")
        monkeypatch.setattr(runner, "RADNI_KOREN", tmp_path)
        monkeypatch.setattr(runner, "moze_da_se_proveri", lambda: moze)
        monkeypatch.setattr(runner, "docker_vidi_isto", lambda _k: vidi)
        monkeypatch.setattr(runner, "api", lambda p, t=None: {"tasks": []})
        monkeypatch.setattr(runner, "PAUZA", 0)

        def stani(_):
            raise KeyboardInterrupt

        monkeypatch.setattr(runner.time, "sleep", stani)
        return runner

    def test_nevidljiv_koren_zaustavlja_poslusnika(
            self, runner, monkeypatch, tmp_path):
        """Ne kreće se. Svaki zadatak bi pao, a krivica bi pala na agenta."""
        r = self._main(runner, monkeypatch, tmp_path, moze=True, vidi=False)
        assert r.main() == 3

    def test_vidljiv_koren_pusta_poslusnika(self, runner, monkeypatch, tmp_path):
        r = self._main(runner, monkeypatch, tmp_path, moze=True, vidi=True)
        with pytest.raises(KeyboardInterrupt):      # stiglo se do petlje
            r.main()

    def test_bez_dockera_se_ne_staje(self, runner, monkeypatch, tmp_path):
        """Demon ume da kasni za servisom; to prođe samo od sebe."""
        r = self._main(runner, monkeypatch, tmp_path, moze=False, vidi=False)
        with pytest.raises(KeyboardInterrupt):
            r.main()

    def test_koren_koji_ne_postoji_zaustavlja(self, runner, monkeypatch, tmp_path):
        r = self._main(runner, monkeypatch, tmp_path / "nema", moze=True, vidi=True)
        assert r.main() == 2

    def test_zaostali_primerci_se_brisu(self, runner, tmp_path):
        for ime in ("rad-a", "izv-b", "proba-c"):
            (tmp_path / ime).mkdir()
        (tmp_path / "tudje").mkdir()
        assert runner.pospremi(tmp_path) == 3
        assert [p.name for p in tmp_path.iterdir()] == ["tudje"]

    def test_provera_ne_pita_docker_bez_slike(self, runner, monkeypatch):
        """Nedostatak slike nije nevidljiv koren — ne meša se jedno s drugim."""
        pozvano = []

        def lazni(*argv, **kw):
            pozvano.append(argv)

            class R:
                returncode = 0 if argv[1] == "version" else 1
                stdout, stderr = "28.0.0", ""
            return R()

        monkeypatch.setattr(runner, "trci", lazni)
        assert runner.moze_da_se_proveri() is False
        assert [a[1] for a in pozvano] == ["version", "image"]

    def test_bez_docker_binarnog_fajla_nije_pad(self, runner, monkeypatch):
        def nema(*a, **k):
            raise FileNotFoundError("docker")

        monkeypatch.setattr(runner, "trci", nema)
        assert runner.moze_da_se_proveri() is False
