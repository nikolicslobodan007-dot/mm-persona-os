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
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    *PERSONA_OS_APPS,
    # F8 (ADR-0010): kontrolna tabla. Nije domen Canon §1, pa nije pod apps/.
    "console",
]

# Canon §8.4 — kontekst zahteva (X-Request-ID, traceparent, X-Actor-ID) se
# postavlja pre bilo čega drugog, da i greška iz middleware-a nosi trace_id.
MIDDLEWARE = [
    "api.middleware.RequestContextMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # API je csrf_exempt (DRF APIView + token); CSRF štiti formulare konzole.
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
STATIC_URL = "/static/"
X_FRAME_OPTIONS = "DENY"

# F8 (ADR-0010) — konzola: sesija 8 h, prijava + TOTP.
LOGIN_URL = "/console/login"
SESSION_COOKIE_AGE = 8 * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
CONSOLE_LOGIN_MAX_FAILURES = 5
CONSOLE_LOGIN_LOCKOUT_SECONDS = 15 * 60

# Canon §8 — API. Samo token prijava: API koriste servisi i skripte, a
# sesija bi uvela CSRF na svaki upis bez ikakve koristi (ADR-0004).
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "api.errors.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MM Persona OS API",
    "VERSION": "1.0.0",
    "DESCRIPTION": "Canon v1.1 §8. Interni API — nije javni.",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
}

# Canon §7.4 — outbox. U testovima se isporuka radi odmah posle commit-a,
# bez Celery-ja; u produkciji je radi `observability.publish_outbox`.
EVENT_BUS_EAGER = False
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

# ---------------------------------------------------------------- F6 (ADR-0008)
# Canon §12.8 t.1 — hladna pošta NIKADA sa ovih domena ni njihovih poddomena.
PRIMARY_COMPANY_DOMAINS = [
    d.strip().lower()
    for d in os.environ.get(
        "PRIMARY_COMPANY_DOMAINS",
        "webkorporacija.com,mercatomaster.com,biznisplan.net",
    ).split(",")
    if d.strip()
]
# Identifikacija pošiljaoca u podnožju poruke (Zakon o elektronskoj trgovini).
COMPANY_LEGAL_NAME = os.environ.get("COMPANY_LEGAL_NAME", "")
# Javna adresa za link odjave (RFC 8058).
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://os.webkorporacija.com")
# Odmah poslati posao worker-u posle ALLOW. Bez ovoga ga pokupi beat za ≤ 15 s.
RUNTIME_KICK = os.environ.get("RUNTIME_KICK", "false").lower() == "true"

# ---------------------------------------------------------------- F7 (ADR-0009)
# Prozor „post” u buđenju pravi nacrt (i predlog objave ako postoji dozvoljen kanal).
CONTENT_AUTODRAFT = os.environ.get("CONTENT_AUTODRAFT", "true").lower() == "true"
# U dev-u odmah posle commit-a; u produkciji kroz Celery (persona.scheduled).
CONTENT_ASYNC = False
# Spoljni LLM samo uz izričito uključivanje; bez toga radi lokalni šablon.
LLM_EXTERNAL_ENABLED = os.environ.get("LLM_EXTERNAL_ENABLED", "false").lower() == "true"
# provider → credential_ref (env:/file:). Tajna nikad u bazi.
LLM_CREDENTIALS = {"anthropic": "env:ANTHROPIC_API_KEY"}
#: ADR-0013 — svaka persona može imati svoj ključ (`ANTHROPIC_API_KEY_P00001`).
#: true = persona bez svog ključa ne koristi zajednički, nego lokalni šablon.
LLM_REQUIRE_PERSONA_KEY = os.environ.get("LLM_REQUIRE_PERSONA_KEY", "false").lower() == "true"
LLM_BASE_URLS: dict[str, str] = {}
