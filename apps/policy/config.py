"""Konfiguracija policy engine-a iz YAML-a. Canon §6.4, §9.2–9.3.

`policy/capabilities.yaml` i `policy/risk_weights.yaml` su izvor istine;
kod ih samo čita. Verzija pravila (`policy_version`) upisuje se u svaku
odluku, pa se stara odluka uvek može objasniti starim brojevima.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings

from common import enums as E

_TRUST_ORDER = {lvl: i for i, lvl in enumerate(E.TrustLevel)}


def trust_at_least(level: E.TrustLevel | str, minimum: E.TrustLevel | str) -> bool:
    return _TRUST_ORDER[E.TrustLevel(level)] >= _TRUST_ORDER[E.TrustLevel(minimum)]


def _load(name: str) -> dict[str, Any]:
    path = Path(settings.BASE_DIR) / "policy" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def capabilities() -> dict[str, Any]:
    return _load("capabilities.yaml")


@lru_cache(maxsize=1)
def weights() -> dict[str, Any]:
    return _load("risk_weights.yaml")


def policy_version() -> str:
    return str(weights()["policy_version"])


def action_types() -> dict[str, list[str]]:
    return capabilities()["action_types"]


def capability(name: str) -> dict[str, Any] | None:
    return capabilities()["capabilities"].get(name)


def rate_limits() -> dict[str, int]:
    return capabilities()["rate_limits_per_persona_day"]


def hard_prohibitions() -> list[dict[str, Any]]:
    return capabilities()["hard_prohibitions"]
