"""Django podešavanja — zajednička osnova. Canon v1.1 §1, §10.5, §11."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-a-secret")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

# Canon §1 — dvanaest app-ova. Redosled prati tabelu iz Canon-a.
PERSONA_OS_APPS = [
    "apps.personas",
    "apps.visuals",
    "apps.behaviour",
    "apps.memory",
    "apps.social_graph",
    "apps.content",
    "apps.channels",
    "apps.orchestration",
    "apps.policy",
    "apps.runtime",
    "apps.observability",
    "apps.llm_gateway",
]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.postgres",
    *PERSONA_OS_APPS,
]

MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "persona_os"),
        "USER": os.environ.get("POSTGRES_USER", "persona"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "persona"),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": int(os.environ.get("POSTGRES_PORT", "5432")),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Canon §4.2, §7.1 — sve je UTC. Lokalno vreme postoji samo u rutinama persone.
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "sr-latn"

# Canon §10.5 — dimenzija embedding-a NIKADA nije hardkodovana u modelu.
# Promena modela traži novu kolonu i backfill, ne izmenu postojeće.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))

# Canon §11.1 — beat na 30 s, lookahead 90 s. Pet minuta ne može da ispuni
# SLO „due lag p95 < 60 s" iz Faze 14.
SCHEDULER_BEAT_SECONDS = 30
SCHEDULER_LOOKAHEAD_SECONDS = 90
SCHEDULER_BATCH_SIZE = 500

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = None  # Postgres je izvor istine, ne Redis (Canon §11)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Canon §12 — runtime. Playwright, bez stealth forkova (§12.1).
BROWSER_ENGINE = "playwright"
BROWSER_LEASE_TTL_SECONDS = 90
BROWSER_HEARTBEAT_SECONDS = 20
BROWSER_MAX_CONTEXTS_PER_WORKER = 4
BROWSER_MAX_WRITE_PER_PERSONA = 1
BROWSER_MAX_READ_PER_PERSONA = 3

# Canon §6.4, §12.6 — obavezni parametri za web.read_public.
WEB_READ_USER_AGENT = os.environ.get(
    "WEB_READ_USER_AGENT",
    "MercatoMasterBot/1.0 (+https://mercatomaster.com/bot; bot@mercatomaster.com)",
)
WEB_READ_RATE_PER_HOST_QPS = 1.0
WEB_READ_RESPECT_ROBOTS = True
WEB_READ_CONDITIONAL_GET = True

# Canon §9 — policy. Fail-closed: bez odgovora nema izvršenja (§12.4).
POLICY_DEFAULT_PROFILE = "creator_standard_v1"
POLICY_FAIL_CLOSED = True
POLICY_EVAL_TIMEOUT_SECONDS = 2

# Canon §13.1 — jedna valuta, celi centi. `llm_usd` ne postoji.
COST_CURRENCY = "EUR"

AUDIT_APPEND_ONLY = True
GLOBAL_EXTERNAL_ACTIONS_ENABLED = os.environ.get(
    "GLOBAL_EXTERNAL_ACTIONS_ENABLED", "false"
).lower() == "true"
