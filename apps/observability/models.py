"""Audit, metrike i trošak. Canon v1.1 §1, §13, §16.5.

Odstupanja od Database & Django Schema v0.1 (Canon §0 — Canon ima prvenstvo):

  - `CostLedger` je prepisan po Canon §13.1. Šema je imala `cost_amount`
    `Decimal(20,8)` uz `currency ∈ {EUR, USD}`; Canon ima JEDNU valutu i
    cele centе: `amount_eur_cents` (`BigInteger`), uz `source_currency`,
    `source_amount_minor`, `fx_rate` i `fx_date`. Razlog nije pedantnost —
    dva reda u dve valute se ne mogu sabrati bez kursa i datuma, a cost
    governor iz §13.3 sabira svakog sata.
  - `service` → `cost_bucket` sa enum-om iz §13.2. `x_api_credits` je
    zaseban bucket jer X naplaćuje po pojedinačnoj objavi.
  - Kurs je dnevni ECB referentni, keširan; `fx_date` je dan NASTANKA
    troška. Konverzija u letu po zahtevu nije dozvoljena (§13.1).
  - `AuditEvent` i `MetricPoint` zadržavaju `BigAutoField` iz šeme: to su
    jedine tabele gde je sekvencijalni ključ bolji od UUID-a, jer se čitaju
    isključivo hronološki i particionišu po vremenu.
  - `run` je dodat svuda — Canon §2.3 traži da se trošak i trag vežu za
    buđenje persone, ne samo za personu.
"""

from __future__ import annotations

from django.db import models

from common import enums as E
from common.models import JSON_DICT


class AuditEvent(models.Model):
    """Append-only sigurnosni i poslovni audit. Canon §16.5.

    `audit_completeness = 100%` je hard KPI pilota: svaka akcija mora imati
    pun trag `proposed → decision → attempt → outcome`. Ova tabela je mesto
    gde se to broji, pa se iz nje ništa ne briše i ništa ne menja —
    `AUDIT_APPEND_ONLY` u podešavanjima nije preporuka.
    """

    id = models.BigAutoField(primary_key=True)
    occurred_at = models.DateTimeField()
    severity = models.CharField(max_length=16, choices=E.AuditSeverity.choices())
    event_key = models.CharField(max_length=120)

    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    run = models.ForeignKey(
        "orchestration.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.ForeignKey(
        "orchestration.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_ref = models.CharField(
        max_length=180, blank=True, help_text="Čovek ili servis koji je izazvao događaj."
    )
    actor_role = models.CharField(
        max_length=24, choices=E.Role.choices(), null=True, blank=True
    )
    trace_id = models.UUIDField(null=True, blank=True)
    payload = JSON_DICT(help_text="Sanitizovano — bez tajni (Canon §17).")
    payload_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "observability_audit_event"
        indexes = [
            models.Index(fields=["occurred_at"]),
            models.Index(fields=["event_key", "occurred_at"]),
            models.Index(fields=["persona", "occurred_at"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_key} @{self.occurred_at:%Y-%m-%d %H:%M:%S}"


class MetricPoint(models.Model):
    """Operativna metrika u vremenu.

    `dimensions` je namerno ograničene kardinalnosti: metrika sa dimenzijom
    koja uzima hiljade vrednosti nije metrika nego log, i ide u `AuditEvent`.
    """

    id = models.BigAutoField(primary_key=True)
    metric = models.CharField(max_length=120)
    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metric_points",
    )
    channel_type = models.CharField(
        max_length=24, choices=E.ChannelType.choices(), null=True, blank=True
    )
    value = models.DecimalField(max_digits=20, decimal_places=6)
    unit = models.CharField(max_length=24, blank=True)
    recorded_at = models.DateTimeField()
    dimensions = JSON_DICT(help_text="Ograničena kardinalnost — vidi docstring.")

    class Meta:
        db_table = "observability_metric_point"
        indexes = [
            models.Index(fields=["metric", "recorded_at"]),
            models.Index(fields=["persona", "recorded_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.metric}={self.value}"


class CostLedger(models.Model):
    """Trošak u EUR centima, po personi i po buđenju. Canon §13.1–13.3.

    Sve je ceo broj u centima. Decimalni iznos u EUR nigde se ne čuva —
    zaokruživanje se radi jednom, pri upisu, i posle toga zbir od milion
    redova daje isti rezultat bez obzira na redosled sabiranja.
    """

    id = models.BigAutoField(primary_key=True)
    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cost_entries",
    )
    run = models.ForeignKey(
        "orchestration.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cost_entries",
    )
    action = models.ForeignKey(
        "orchestration.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cost_entries",
    )
    cost_bucket = models.CharField(max_length=24, choices=E.CostBucket.choices())
    provider = models.CharField(max_length=80)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    unit = models.CharField(max_length=32)  # tokens/images/sec/GB/posts

    amount_eur_cents = models.BigIntegerField(help_text="Kanonska valuta (Canon §13.1).")
    source_currency = models.CharField(max_length=3, default="EUR")
    source_amount_minor = models.BigIntegerField(
        help_text="Iznos u najmanjoj jedinici izvorne valute."
    )
    fx_rate = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=1,
        help_text="Dnevni ECB referentni kurs, keširan.",
    )
    fx_date = models.DateField(help_text="Dan NASTANKA troška, ne dan obračuna.")

    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    provider_ref = models.CharField(max_length=160, blank=True)

    class Meta:
        db_table = "observability_cost_ledger"
        indexes = [
            models.Index(fields=["persona", "occurred_at"]),
            models.Index(fields=["cost_bucket", "occurred_at"]),
            models.Index(fields=["provider", "occurred_at"]),
            models.Index(fields=["run"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_eur_cents__gte=0),
                name="cost_ledger_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(fx_rate__gt=0), name="cost_ledger_fx_rate_positive"
            ),
            models.CheckConstraint(
                # EUR trošak sa kursom različitim od 1 znači grešku u konverziji.
                condition=~models.Q(source_currency="EUR") | models.Q(fx_rate=1),
                name="cost_ledger_eur_rate_is_one",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cost_bucket} {self.amount_eur_cents}c"
