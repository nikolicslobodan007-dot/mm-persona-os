"""Pristup konzoli. ADR-0010.

  - Prijava: korisničko ime + lozinka, zatim TOTP kod. Tek posle oba koraka
    postoji sesija; bez drugog faktora nema pristupa ni jednoj strani.
  - Zaključavanje: 5 neuspeha po (IP, korisnik) → 15 min pauze (Redis keš).
  - Samo korisnici sa bar jednom Canon ulogom (ili superuser).
  - Svaki upis ide kroz servisni sloj uz `bind(actor_id="user:<ime>")`, pa je
    u audit-u isti akter kao da je išao kroz API.
"""

from __future__ import annotations

import functools

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from api.base import principal_of, roles_of
from api.context import bind

SESSION_OTP = "console_otp_ok"
SESSION_PENDING = "console_pending_uid"
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")


def client_ip(request) -> str:
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


def _key(request, username: str) -> str:
    return f"console:fail:{client_ip(request)}:{username.strip().lower()}"


def locked(request, username: str) -> bool:
    return int(cache.get(_key(request, username), 0)) >= settings.CONSOLE_LOGIN_MAX_FAILURES


def record_failure(request, username: str) -> None:
    key = _key(request, username)
    if not cache.add(key, 1, settings.CONSOLE_LOGIN_LOCKOUT_SECONDS):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, settings.CONSOLE_LOGIN_LOCKOUT_SECONDS)


def clear_failures(request, username: str) -> None:
    cache.delete(_key(request, username))


def is_operator(user) -> bool:
    return bool(user and user.is_active and (user.is_superuser or roles_of(user)))


def secure(response):
    response["Content-Security-Policy"] = CSP
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def console_view(fn):
    """Prijavljen + drugi faktor + uloga. Kontekst akcije = prijavljeni čovek."""

    @functools.wraps(fn)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated or not request.session.get(SESSION_OTP):
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")
        if not is_operator(user):
            return secure(HttpResponseForbidden("Nemaš ulogu za konzolu."))
        with bind(actor_id=principal_of(user)):
            return secure(fn(request, *args, **kwargs))

    return wrapper
