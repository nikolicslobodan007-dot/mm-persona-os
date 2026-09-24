"""Produkcijska podešavanja.

Ovde je samo ono bez čega gunicorn ne može da se podigne iza Caddy-ja.
Puno F9 očvršćavanje (Canon §18) — Keycloak/OIDC, audit sink, OTel exporter,
rate limiting na ivici — dolazi kasnije i ne ide u ovaj fajl bez ADR-a.
"""

import os

from config.settings.base import *  # noqa: F401,F403

DEBUG = False

if not os.environ.get("DJANGO_SECRET_KEY"):
    raise RuntimeError("DJANGO_SECRET_KEY nije postavljen. Produkcija ne sme na default.")

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()
]
if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS je prazan.")

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# Caddy terminira TLS; Django o tome saznaje isključivo preko ovog zaglavlja.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Aplikacije, middleware i šabloni su u base-u od F8 (ADR-0010) — konzola ih
# traži i u testovima. Ovde ostaje samo ono što važi isključivo iza HTTPS-a.

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
# HSTS i HTTP→HTTPS preusmeravanje radi Caddy, ne Django.
# Zato `check --deploy` prijavljuje W004 i W008 — to je namerno, ne propust.
# Ako se Caddy ikad zameni, ova dva podešavanja se uključuju ovde.

STATIC_ROOT = "/app/staticfiles"
#: Ime fajla dobija hash sadržaja (`console.a1b2c3.css`), pa pregledač posle
#: izmene stila više ne servira stari iz keša (nalaz 24.09.). Samo u produkciji —
#: u razvoju i testovima nema `collectstatic`, pa nema ni manifesta.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
    },
}
STATIC_URL = "/static/"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# Sav log ide na stdout; Docker ga rotira po /etc/docker/daemon.json.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        # Canon §16 — audit trag se nikada ne guši na nivou logovanja.
        "persona.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# F6 (ADR-0008): tempo po hostu, robots.txt i ETag keš moraju biti zajednički
# za sve worker-e — zato Redis, ne memorija procesa. Baza 1, broker je na 0.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("CACHE_URL", "redis://redis:6379/1"),
        "TIMEOUT": 300,
    }
}
RUNTIME_KICK = os.environ.get("RUNTIME_KICK", "true").lower() == "true"
CONTENT_ASYNC = True
