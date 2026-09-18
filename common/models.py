"""Zajedničke apstraktne baze za sve modele — Canon v1.1 §2.

Ovde ne živi nijedan konkretan model. Svaki app definiše svoje tabele,
ali svi nasleđuju identifikatore i vremenske pečate odavde da bi
konvencija iz Canon §2 bila jedno mesto, a ne dvanaest.
"""

from __future__ import annotations

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

__all__ = [
    "UUIDModel",
    "unit_interval",
    "risk_score_field",
    "JSON_DICT",
    "JSON_LIST",
]


def JSON_DICT(**kwargs):  # noqa: N802 — čita se kao tip, ne kao funkcija
    """JSONField sa `{}` podrazumevanom vrednošću.

    Canon §2: JSONB samo za retko menjajuće ili provider-specific payload-e;
    poslovno kritična polja ostaju normalizovana.
    """
    kwargs.setdefault("default", dict)
    kwargs.setdefault("blank", True)
    return models.JSONField(**kwargs)


def JSON_LIST(**kwargs):  # noqa: N802
    kwargs.setdefault("default", list)
    kwargs.setdefault("blank", True)
    return models.JSONField(**kwargs)


def unit_interval(**kwargs) -> models.DecimalField:
    """Normalizovana vrednost 0..1 — Decimal(4,3), nikada float.

    Canon §3.6 izričito razdvaja ovaj opseg od `risk_score`, koji je
    ceo broj 0–100. Decimal je izabran jer float ne može tačno da
    predstavi 0.1 i poređenja u CHECK ograničenjima postaju nepouzdana.
    """
    kwargs.setdefault("max_digits", 4)
    kwargs.setdefault("decimal_places", 3)
    kwargs.setdefault(
        "validators", [MinValueValidator(0), MaxValueValidator(1)]
    )
    return models.DecimalField(**kwargs)


def risk_score_field(**kwargs) -> models.PositiveSmallIntegerField:
    """Canon §3.6 — ceo broj 0–100, svojstvo ZAHTEVA a ne odluke.

    Zona (GREEN/YELLOW/RED) se NIKADA ne upisuje: ona je izvedena iz
    `PolicyEffect` kroz `EFFECT_TO_ZONE`.
    """
    kwargs.setdefault(
        "validators", [MinValueValidator(0), MaxValueValidator(100)]
    )
    return models.PositiveSmallIntegerField(**kwargs)


class UUIDModel(models.Model):
    """Canon §2.1 — interni ključ je UUIDv4 i nikada nije javni identifikator."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
