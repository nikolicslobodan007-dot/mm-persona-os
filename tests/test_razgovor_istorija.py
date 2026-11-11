"""ADR-0135 — direktor procenjuje sa istorijom niti (ne vrti u krug)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.orchestration import razgovor as nit
from apps.orchestration.models import Poruka, Razgovor
from tests.conftest import requires_db


@requires_db
@pytest.mark.django_db
def test_istorija_niti_redom_i_osim(mila):
    r = Razgovor.objects.create(persona=mila, human_owner="user:qa", naslov="t")
    Poruka.objects.create(razgovor=r, autor=Poruka.OD_COVEKA,
                          autor_ref="user:qa", telo="https://fb.com/reel/123")
    Poruka.objects.create(razgovor=r, autor=Poruka.OD_AGENTA,
                          autor_ref=mila.public_id, telo="Koji video?")
    tekuca = Poruka.objects.create(razgovor=r, autor=Poruka.OD_COVEKA,
                                   autor_ref="user:qa", telo="reši ovaj video")

    ist = nit._istorija_niti(r, osim=tekuca.id)
    assert "Vlasnik: https://fb.com/reel/123" in ist
    assert "Direktor: Koji video?" in ist
    assert "reši ovaj video" not in ist          # tekuća poruka isključena
    assert ist.index("fb.com") < ist.index("Koji video")  # hronološki redom


def test_razmisli_ubacuje_istoriju(monkeypatch):
    from apps.llm_gateway import gateway

    captured: dict = {}

    def fake(purpose, system, prompt, **kw):
        captured["prompt"] = prompt
        return SimpleNamespace(text="{}")

    monkeypatch.setattr(gateway, "generate", fake)
    nit.razmisli(SimpleNamespace(public_id="P-0"), "reši ovaj video",
                 istorija="Vlasnik: https://fb.com/reel/123")

    assert "Dosadašnji razgovor" in captured["prompt"]
    assert "fb.com/reel/123" in captured["prompt"]   # link iz istorije vidljiv
    assert "reši ovaj video" in captured["prompt"]   # i tekuća poruka
