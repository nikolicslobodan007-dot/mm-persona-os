"""TOTP po RFC 6238 (SHA-1, 30 s, 6 cifara) — radi sa svakom aplikacijom za kodove."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.db import transaction

from console.models import OperatorTOTP

STEP = 30
DIGITS = 6
ISSUER = "MM Persona OS"


def secret_for(username: str, version: int) -> bytes:
    msg = f"console-totp:{username}:{version}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).digest()[:20]


def b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode().rstrip("=")


def code_at(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    n = struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF
    return str(n % 10 ** DIGITS).zfill(DIGITS)


def provisioning_uri(username: str, version: int) -> str:
    label = quote(f"{ISSUER}:{username}")
    return (f"otpauth://totp/{label}?secret={b32(secret_for(username, version))}"
            f"&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP}")


def verify(user, code: str, *, now: float | None = None) -> bool:
    """Prozor ±1 korak; isti kod se ne prima dvaput (last_step)."""
    code = "".join(c for c in (code or "") if c.isdigit())
    if len(code) != DIGITS:
        return False
    step_now = int((now if now is not None else time.time()) // STEP)
    with transaction.atomic():
        rec = OperatorTOTP.objects.select_for_update().filter(user=user).first()
        if rec is None:
            return False
        secret = secret_for(user.get_username(), rec.version)
        for step in (step_now - 1, step_now, step_now + 1):
            if step > rec.last_step and hmac.compare_digest(code_at(secret, step), code):
                rec.last_step = step
                if rec.confirmed_at is None:
                    from django.utils import timezone

                    rec.confirmed_at = timezone.now()
                rec.save(update_fields=["last_step", "confirmed_at"])
                return True
    return False
