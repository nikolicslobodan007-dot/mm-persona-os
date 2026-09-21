"""Matrica izvršenja po kanalu (`channels/platforms.yaml`). ADR-0008."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = _ROOT / "channels" / "platforms.yaml"


@lru_cache(maxsize=1)
def platforms() -> dict[str, Any]:
    return yaml.safe_load(PLATFORMS.read_text(encoding="utf-8"))


def channel(channel_type: str) -> dict[str, Any]:
    return platforms()["channels"].get(channel_type) or {}


def api_version(key: str) -> str:
    return str(platforms()["api_versions"][key])


def fx_usd_eur() -> Decimal:
    return Decimal(str(platforms()["fx_usd_eur"]))


def action_spec(channel_type: str, action_type: str) -> dict[str, Any] | None:
    """Specifikacija akcije na kanalu, ili None ako put ne postoji."""
    spec = (channel(channel_type).get("actions") or {}).get(action_type)
    return None if spec is None else dict(spec)


def unavailable_reason(channel_type: str, action_type: str) -> str | None:
    return (channel(channel_type).get("unavailable") or {}).get(action_type)


def matrix() -> list[dict[str, Any]]:
    """Ceo pregled: kanal × tip akcije → dostupno ili razlog zašto nije."""
    from apps.policy import config as policy_config

    rows = []
    for ch, spec in platforms()["channels"].items():
        for at in policy_config.action_types():
            if at.startswith(("content.", "memory.")):
                continue
            ok = at in (spec.get("actions") or {})
            reason = (spec.get("unavailable") or {}).get(at)
            if ok or reason:
                rows.append({"channel_type": ch, "action_type": at, "available": ok,
                             "adapter": spec.get("adapter") if ok else None,
                             "reason": None if ok else reason})
    return rows
