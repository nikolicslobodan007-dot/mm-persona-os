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
