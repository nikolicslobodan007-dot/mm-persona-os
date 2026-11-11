"""ADR-0137 — demand-driven autopilot: dnevni ulov ide ka prazninama ekipe."""

from __future__ import annotations

import pytest

from tests.conftest import requires_db


@requires_db
@pytest.mark.django_db
def test_praznine_ekipe_hvata_nise(mila, monkeypatch):
    from apps.memory import context
    from apps.memory.management.commands.potraznja import praznine_ekipe

    monkeypatch.setattr(context, "najbliza_distanca", lambda q: 0.7)  # sve daleko
    monkeypatch.setattr(context, "broj_u_diviziji", lambda s: 0)
    slugs = {g["slug"] for g in praznine_ekipe(prag=0.45)}
    assert {"ai", "b2b", "sales"} <= slugs  # Miline niše = praznine

    monkeypatch.setattr(context, "najbliza_distanca", lambda q: 0.2)  # sve blizu
    assert praznine_ekipe(prag=0.45) == []


def test_dnevni_task_teme_union_sa_prazninama(monkeypatch):
    import django.core.management as dm

    from apps.memory import tasks
    from apps.memory.management.commands import potraznja

    monkeypatch.setattr(potraznja, "praznine_ekipe",
                        lambda *a, **k: [{"slug": "podcasting", "naziv": "Podkasti",
                                          "najbliza": 0.7, "u_domenu": 0}])
    pozivi: list = []

    def fake(name, **kw):
        pozivi.append(kw)
        if kw.get("stdout") is not None:
            kw["stdout"].write("linija izveštaja")

    monkeypatch.setattr(dm, "call_command", fake)
    tasks.github_signals_dnevno()

    auto = next(p for p in pozivi if p.get("auto"))
    assert "podcasting" in auto["teme"]   # praznina ubačena u ulov
    assert "ai agent" in auto["teme"]     # default zadržan (union, ne skida manje)
