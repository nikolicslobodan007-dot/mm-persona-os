"""Centralna lista odjava. Canon §12.8 t.6 · ADR-0008.

Čuva se samo hash adrese. Link za odjavu nosi potpisan token sa hash-om,
pa ni URL ne otkriva adresu.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction

from apps.channels.models import SuppressionEntry
from common import enums as E

_SALT = "mail.unsubscribe.v1"


def normalize(address: str) -> str:
    return (address or "").strip().lower()


def address_hash(address: str) -> str:
    return hashlib.sha256(normalize(address).encode()).hexdigest()


def domain_hash(address_or_domain: str) -> str:
    d = normalize(address_or_domain).rpartition("@")[2]
    return hashlib.sha256(d.encode()).hexdigest()


def is_suppressed(address: str) -> bool:
    return SuppressionEntry.objects.filter(address_hash=address_hash(address)).exists() or \
        SuppressionEntry.objects.filter(address_hash="",
                                        domain_hash=domain_hash(address)).exists()


def suppress_hash(ahash: str, reason: E.SuppressionReason, *, source: str,
                  actor: str = "") -> tuple[SuppressionEntry, bool]:
    try:
        with transaction.atomic():
            return SuppressionEntry.objects.create(address_hash=ahash, reason=reason.value,
                                                   source=source, created_by=actor), True
    except IntegrityError:
        return SuppressionEntry.objects.get(address_hash=ahash), False


def suppress(address: str, reason: E.SuppressionReason, *, source: str, actor: str = ""):
    return suppress_hash(address_hash(address), reason, source=source, actor=actor)


def suppress_domain(domain: str, *, source: str, actor: str = ""):
    h = domain_hash(domain)
    try:
        with transaction.atomic():
            return SuppressionEntry.objects.create(domain_hash=h,
                                                   reason=E.SuppressionReason.MANUAL.value,
                                                   source=source, created_by=actor), True
    except IntegrityError:
        return SuppressionEntry.objects.get(address_hash="", domain_hash=h), False


def token_for(address: str) -> str:
    return signing.dumps({"h": address_hash(address)}, salt=_SALT, compress=True)


def hash_from_token(token: str) -> str | None:
    try:
        return signing.loads(token, salt=_SALT)["h"]
    except (signing.BadSignature, KeyError, TypeError):
        return None


def unsubscribe_url(address: str) -> str:
    base = getattr(settings, "PUBLIC_BASE_URL", "https://os.webkorporacija.com").rstrip("/")
    return f"{base}/api/v1/mail/unsubscribe?t={token_for(address)}"
