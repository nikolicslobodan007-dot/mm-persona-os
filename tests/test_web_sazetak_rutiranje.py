"""ADR-0139 — rutiranje zadatka po vrsti: „pregledaj link i sažmi" ide na web.sazetak."""

from __future__ import annotations

from types import SimpleNamespace

from apps.content import service as content_service
from apps.llm_gateway import gateway
from apps.memory.sakupljanje import steps, ulaz
from apps.orchestration import plans
from apps.orchestration import razgovor as nit


def test_procitaj_odluku_vrsta_sazetak_weba():
    d = nit._procitaj_odluku(
        '{"sektor":"RAZVOJ","nalog":"pregledaj","pitanje":"",'
        '"vrsta":"sazetak-weba","url":"https://github.com/kong/insomnia"}',
        {"RAZVOJ", "UPRAVA"})
    assert d["vrsta"] == "sazetak-weba"
    assert d["url"] == "https://github.com/kong/insomnia"


def test_koraci_sazetak_rutira_na_web_sazetak():
    sef = SimpleNamespace(display_name="Šef", public_id="P-10")
    izv = SimpleNamespace(display_name="Izv", public_id="P-11")
    plosnato = str(nit._koraci("pregledaj ovaj repo", sef, izv,
                               vrsta="sazetak-weba", url="https://x/repo"))
    assert "web.sazetak" in plosnato
    assert "https://x/repo" in plosnato
    assert "content.draft" not in plosnato  # NE generički pisac


def test_handler_bez_url_staje():
    step = SimpleNamespace(input_json={}, plan=SimpleNamespace(persona=None))
    assert isinstance(steps._sazetak(step, {}), plans.Failed)


def test_handler_prazan_tekst_staje(monkeypatch):
    monkeypatch.setattr(ulaz, "procitaj", lambda vrsta, url: {"tekst": "  ", "naslov": "x"})
    step = SimpleNamespace(input_json={"url": "https://x/repo"},
                           plan=SimpleNamespace(persona=None))
    assert isinstance(steps._sazetak(step, {}), plans.Failed)


def test_handler_sazima(monkeypatch):
    monkeypatch.setattr(ulaz, "procitaj",
                        lambda vrsta, url: {"tekst": "Ovo je alat za API.",
                                            "naslov": "Insomnia", "izvor": url})
    monkeypatch.setattr(content_service, "_system_prompt", lambda p: "sys")
    monkeypatch.setattr(gateway, "generate",
                        lambda *a, **kw: SimpleNamespace(text="Insomnia je API klijent."))
    persona = SimpleNamespace(primary_locale="sr-Latn")
    step = SimpleNamespace(input_json={"url": "https://x/repo"},
                           plan=SimpleNamespace(persona=persona, run=None))
    out = steps._sazetak(step, {})
    assert isinstance(out, plans.Done)
    assert out.output["sazetak"] == "Insomnia je API klijent."
    assert out.output["izvor"] == "https://x/repo"
    assert out.output["naslov"] == "Insomnia"
