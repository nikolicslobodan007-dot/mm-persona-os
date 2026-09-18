"""Podizanje Django okruženja za testove modela.

Testovi iz `test_canon.py` ne traže Django i rade i bez ovoga. Testovi iz
`test_models.py` traže učitan registar modela; oni koji dodiruju bazu
nose `@pytest.mark.django_db` i preskaču se ako baza nije dostupna.
"""

from __future__ import annotations

import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()


def _database_available() -> bool:
    """Provera ide pravo kroz drajver.

    `connection.ensure_connection()` ovde ne valja: pytest-django već je
    postavio blokadu pristupa bazi izvan `django_db`, pa bi svaka baza
    izgledala kao nedostupna i ceo DB deo bi se tiho preskakao.
    """
    from django.conf import settings

    db = settings.DATABASES["default"]
    try:
        import psycopg

        psycopg.connect(
            host=db["HOST"],
            port=db["PORT"],
            user=db["USER"],
            password=db["PASSWORD"],
            dbname="postgres",
            connect_timeout=3,
        ).close()
    except Exception:  # noqa: BLE001 — svaki neuspeh znači „nema baze"
        return False
    return True


DB_AVAILABLE = _database_available()

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE, reason="PostgreSQL nije dostupan na ovom hostu"
)
