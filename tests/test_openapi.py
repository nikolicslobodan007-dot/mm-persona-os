"""Ugovor u repou mora biti isti kao ono što kod stvarno servira.

Ako ovaj test padne posle izmene API-ja, regeneriši ugovor i commit-uj ga
zajedno sa izmenom:

    python manage.py spectacular --file contracts/openapi/persona-os-v1.yaml --validate
"""

from __future__ import annotations

from pathlib import Path

import yaml
from drf_spectacular.generators import SchemaGenerator

CONTRACT = Path(__file__).resolve().parent.parent / "contracts/openapi/persona-os-v1.yaml"


def _current() -> dict:
    return SchemaGenerator().get_schema(request=None, public=True)


def test_contract_matches_code():
    on_disk = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert on_disk == yaml.safe_load(yaml.safe_dump(_current())), (
        "OpenAPI ugovor je zastareo — regeneriši ga (vidi docstring)."
    )


def test_every_path_is_under_api_v1():
    assert all(p.startswith("/api/v1/") for p in _current()["paths"])
