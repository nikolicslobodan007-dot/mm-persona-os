"""ADR-0136 — rutiranje zadatka po vrsti: „prepiši video" ide na ASR (klip.prepis)."""

from __future__ import annotations

from types import SimpleNamespace

from apps.memory.veritas import klip, steps
from apps.orchestration import plans
from apps.orchestration import razgovor as nit


def test_procitaj_odluku_vrsta_url():
    d = nit._procitaj_odluku(
        '{"sektor":"RAZVOJ","nalog":"prepiši","pitanje":"",'
        '"vrsta":"prepis-videa","url":"https://x/v"}',
        {"RAZVOJ", "UPRAVA"})
    assert d["vrsta"] == "prepis-videa"
    assert d["url"] == "https://x/v"
    # nepoznata vrsta → objava (podrazumevano)
    assert nit._procitaj_odluku('{"vrsta":"nesto"}', {"UPRAVA"})["vrsta"] == "objava"


def test_koraci_prepis_rutira_na_klip():
    sef = SimpleNamespace(display_name="Šef", public_id="P-10")
    izv = SimpleNamespace(display_name="Izv", public_id="P-11")
    plosnato = str(nit._koraci("prepiši video", sef, izv,
                               vrsta="prepis-videa", url="https://x/v"))
    assert "klip.prepis" in plosnato
    assert "https://x/v" in plosnato
    assert "content.draft" not in plosnato  # NE generički pisac


def test_koraci_objava_ostaje_content_draft():
    sef = SimpleNamespace(display_name="Šef", public_id="P-10")
    plosnato = str(nit._koraci("piši objavu", sef, None))  # vrsta default = objava
    assert "content.draft" in plosnato
    assert "klip.prepis" not in plosnato


def test_handler_bez_url_staje():
    step = SimpleNamespace(input_json={}, plan=SimpleNamespace(persona=None))
    assert isinstance(steps._prepis(step, {}), plans.Failed)


def test_handler_zove_transkribuj(monkeypatch):
    monkeypatch.setattr(klip, "transkribuj",
                        lambda url, **kw: {"transkript": "zdravo svete",
                                           "izvor_url": url, "asset_id": "AUD-1"})
    step = SimpleNamespace(input_json={"url": "https://x/v"},
                           plan=SimpleNamespace(persona=None))
    out = steps._prepis(step, {})
    assert isinstance(out, plans.Done)
    assert out.output["transkript"] == "zdravo svete"
    assert out.output["izvor"] == "https://x/v"


def test_handler_prazan_transkript_staje(monkeypatch):
    monkeypatch.setattr(klip, "transkribuj", lambda url, **kw: {"transkript": "  "})
    step = SimpleNamespace(input_json={"url": "https://x/v"},
                           plan=SimpleNamespace(persona=None))
    assert isinstance(steps._prepis(step, {}), plans.Failed)
