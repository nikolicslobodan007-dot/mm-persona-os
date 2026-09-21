"""Registar adaptera. Kanal × tip akcije → adapter, ili razlog zašto ne postoji."""

from __future__ import annotations

from apps.runtime import config
from apps.runtime.adapters.base import Adapter, Exec, Outcome
from apps.runtime.adapters.mail import MailAdapter
from apps.runtime.adapters.social import (
    FacebookAdapter,
    InstagramAdapter,
    LinkedInAdapter,
    SandboxAdapter,
    XAdapter,
)
from apps.runtime.adapters.web import WebAdapter
from common import enums as E

ADAPTERS: dict[str, Adapter] = {a.key: a for a in (
    SandboxAdapter(), WebAdapter(), MailAdapter(), FacebookAdapter(), InstagramAdapter(),
    LinkedInAdapter(), XAdapter(),
)}


def resolve(channel_type: str | None, action_type: str) -> tuple[Adapter | None, str, str]:
    """(adapter, reason_code, objašnjenje). Bez adaptera → CAPABILITY_UNAVAILABLE."""
    if not channel_type:
        # Čitanje javnog weba ne traži nalog (Canon §6.4); forma traži profil
        # sa allowed_domains, što WebAdapter proverava sam.
        if action_type.startswith("browser."):
            return ADAPTERS["web"], "", ""
        return None, E.RuntimeReason.NO_ADAPTER.value, "Akcija nema kanal."
    spec = config.channel(channel_type)
    if config.action_spec(channel_type, action_type) is not None:
        return ADAPTERS[spec["adapter"]], "", ""
    why = config.unavailable_reason(channel_type, action_type) or \
        f"{channel_type} nema sankcionisan put za {action_type}."
    return None, E.OUTCOME_REASON_CODE[E.ExecutionOutcome.CAPABILITY_UNAVAILABLE], why


__all__ = ["ADAPTERS", "Adapter", "Exec", "Outcome", "resolve"]
