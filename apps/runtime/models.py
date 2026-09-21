"""Browser profili, sesije, poslovi i reconcile. Canon v1.1 §1, §11.3, §12.

Odstupanja od Database & Django Schema v0.1 (Canon §0 — Canon ima prvenstvo):

  - `MailMessage` NIJE ovde. Canon §1 ga daje app-u `channels`, uz
    `ChannelAccount` — pošta je kanal, ne runtime (§3.15, §12.8).
  - `BrowserProfile` dobija šest polja koja šema nema (Canon §12.7):
    `allowed_domains`, `blocked_domains`, `max_session_seconds`,
    `kill_switch_enabled`, `auth_state`, `snapshot_version`.
  - `RuntimeSession` dobija leasing (Canon §12.3): `lease_expires_at` i
    `heartbeat_at`. Bez njih se izgubljeni worker ne razlikuje od sporog,
    pa se posao ili duplira ili zaglavi.
  - Dodat je `ReconcileTask` (Canon §1, §12.3). Reconcile korak je
    OBAVEZAN u Celery grafu i nedostaje u Implementation Pack v0.1 —
    Canon ga vodi kao errata §19. Ovde živi zato što `UNKNOWN_EFFECT`
    nikada ne sme da vodi u retry, nego ovamo.
  - `queue` je izbor iz `QueueName` (Canon §11.3 — deset queue-ova i ni
    jedan više), ne slobodan `CharField(80)`.
  - Engine je Playwright i samo Playwright (Canon §12.1). Stealth fork je
    u koliziji sa §9.4 tačkom 4: sistem čija je vrednost u tome što je
    auditabilan ne sme imati komponentu čija je svrha da bude neprimetan.
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common import enums as E
from common.models import JSON_DICT, UUIDModel


class BrowserProfile(UUIDModel):
    """Izolovani browser kontekst. Nijedan kredencijal se ne čuva ovde.

    Canon §2 i §17: u bazi stoji samo `credential_ref` na `ChannelAccount`-u,
    nikada tajna. `storage_namespace` je granica izolacije između persona —
    curenje memorije ili kredencijala između persona je automatski NO-GO
    uslov pilota (§16.4).
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="browser_profiles"
    )
    name = models.CharField(max_length=120)
    storage_namespace = models.CharField(max_length=220, unique=True)
    engine = models.CharField(
        max_length=32, default="playwright", help_text="Canon §12.1 — samo Playwright."
    )
    locale = models.CharField(max_length=16)
    timezone = models.CharField(max_length=64)
    status = models.CharField(
        max_length=24, choices=E.AccountStatus.choices(), default=E.AccountStatus.PENDING
    )

    # Canon §12.7 — promovisano u kolone.
    allowed_domains = ArrayField(models.CharField(max_length=180), default=list, blank=True)
    blocked_domains = ArrayField(models.CharField(max_length=180), default=list, blank=True)
    max_session_seconds = models.IntegerField(
        default=900, validators=[MinValueValidator(1), MaxValueValidator(7200)]
    )
    kill_switch_enabled = models.BooleanField(default=True)
    auth_state = models.CharField(
        max_length=24, choices=E.AuthState.choices(), default=E.AuthState.UNKNOWN
    )
    snapshot_version = models.IntegerField(default=1)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "runtime_browser_profile"
        indexes = [
            models.Index(fields=["status", "last_used_at"]),
            models.Index(fields=["persona", "auth_state"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "name"], name="browser_profile_unique_name"
            ),
            models.CheckConstraint(
                condition=models.Q(engine="playwright"),
                name="browser_profile_engine_playwright_only",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.persona_id})"


class RuntimeSession(UUIDModel):
    """Jedna kratkotrajna sesija izvršenja. Canon §12.2–12.3.

    Jedinica konkurentnosti je JEDAN browser kontekst = jedna aktivna sesija
    jedne persone; po personi najviše 1 write + 3 read paralelno. To je
    granica koja sprečava da jedna persona zauzme ceo pool.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.PROTECT, related_name="runtime_sessions"
    )
    session_type = models.CharField(max_length=16, choices=E.SessionType.choices())
    browser_profile = models.ForeignKey(
        BrowserProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions",
    )
    run = models.ForeignKey(
        "orchestration.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runtime_sessions",
    )
    is_write = models.BooleanField(
        default=False, help_text="Canon §12.2 — najviše jedna write sesija po personi."
    )
    worker_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=16, choices=E.SessionStatus.choices(), default=E.SessionStatus.OPEN
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(
        null=True, blank=True, help_text="Canon §12.3 — otkucaj na 20 s."
    )
    lease_expires_at = models.DateTimeField(
        null=True, blank=True, help_text="Canon §12.3 — TTL 90 s."
    )
    resource_json = JSON_DICT()
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "runtime_session"
        indexes = [
            models.Index(fields=["persona", "started_at"]),
            models.Index(fields=["status", "started_at"]),
            models.Index(fields=["lease_expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["persona"],
                condition=models.Q(is_write=True, status=E.SessionStatus.OPEN.value),
                name="runtime_session_one_write_per_persona",
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(ended_at__gte=models.F("started_at")),
                name="runtime_session_ends_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.session_type}<{self.persona_id}> {self.status}"


class WorkerJob(UUIDModel):
    """Jedinica rada u queue-u. Canon §11.3, §12.4.

    Nije isto što i `AgentRun` (poslovni pojam) ni `RuntimeSession`
    (tehnička sesija) — Canon §1 ih izričito razdvaja. `max_attempts`
    prati §12.4: read 3, write 2, policy 1 bez retry-ja.
    """

    action = models.ForeignKey(
        "orchestration.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
    )
    session = models.ForeignKey(
        RuntimeSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
    )
    job_type = models.CharField(max_length=64)
    queue = models.CharField(max_length=24, choices=E.QueueName.choices())
    status = models.CharField(
        max_length=16, choices=E.JobStatus.choices(), default=E.JobStatus.PENDING
    )
    attempt = models.SmallIntegerField(default=0)
    max_attempts = models.SmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    run_after = models.DateTimeField()
    locked_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True)
    payload = JSON_DICT(help_text="Sanitizovano — bez tajni (Canon §17).")
    last_error = models.TextField(blank=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True)
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "runtime_worker_job"
        indexes = [
            models.Index(fields=["queue", "status", "run_after"]),
            models.Index(fields=["action"]),
            models.Index(
                fields=["queue", "run_after"],
                # Canon §18 (šema) — claim bez punog skeniranja tabele.
                condition=models.Q(
                    status__in=[E.JobStatus.PENDING.value, E.JobStatus.RETRY.value]
                ),
                name="worker_job_claimable_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(attempt__lte=models.F("max_attempts")),
                name="worker_job_attempt_within_max",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.job_type}@{self.queue} {self.status}"


class ReconcileTask(UUIDModel):
    """Provera da li je spoljašnji efekat nastao. Canon §12.3, §16.5.

    Jedini put za `UNKNOWN_EFFECT`. Retry je ovde zabranjen po definiciji:
    dok se ne utvrdi da efekta nema, ponovni pokušaj bi bio duplirani
    spoljašnji efekat — a to je automatski NO-GO uslov pilota (§16.4).
    Udeo akcija sa poznatim konačnim ishodom (`action_accounting ≥ 99%`)
    meri se upravo iz ove tabele.
    """

    action = models.ForeignKey(
        "orchestration.Action", on_delete=models.CASCADE, related_name="reconcile_tasks"
    )
    attempt = models.ForeignKey(
        "orchestration.ActionAttempt",
        on_delete=models.CASCADE,
        related_name="reconcile_tasks",
    )
    status = models.CharField(
        max_length=32,
        choices=E.ReconcileStatus.choices(),
        default=E.ReconcileStatus.PENDING,
    )
    reason = models.TextField(blank=True)
    check_method = models.CharField(
        max_length=64, blank=True, help_text="api_lookup/browser_verify/provider_search"
    )
    checks = JSON_DICT()
    scheduled_for = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    resolved_at = models.DateTimeField(null=True, blank=True)
    evidence_ref = models.CharField(max_length=512, blank=True)
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "runtime_reconcile_task"
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["action"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt"], name="reconcile_task_unique_attempt"
            ),
            models.CheckConstraint(
                condition=~models.Q(
                    status__in=[
                        E.ReconcileStatus.RESOLVED_EFFECT_PRESENT.value,
                        E.ReconcileStatus.RESOLVED_NO_EFFECT.value,
                    ]
                )
                | models.Q(resolved_at__isnull=False),
                name="reconcile_resolved_has_timestamp",
            ),
        ]

    def __str__(self) -> str:
        return f"reconcile<{self.action_id}> {self.status}"


class CircuitBreaker(UUIDModel):
    """Canon §12.5 — po paru (adapter, nalog).

    CLOSED → OPEN na 5 grešaka u 60 s; HALF_OPEN posle 120 s, 1–3 probe.
    Stanje je u bazi, ne u memoriji worker-a: breaker mora da važi za sve
    worker-e odjednom, i da preživi restart.
    """

    adapter_key = models.CharField(max_length=64)
    account = models.ForeignKey(
        "channels.ChannelAccount", on_delete=models.CASCADE, null=True, blank=True,
        related_name="breakers",
    )
    state = models.CharField(
        max_length=16, choices=E.BreakerState.choices(), default=E.BreakerState.CLOSED
    )
    failures = models.JSONField(default=list, blank=True,
                                help_text="ISO vremena grešaka u prozoru od 60 s.")
    opened_at = models.DateTimeField(null=True, blank=True)
    probes = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "runtime_circuit_breaker"
        constraints = [
            models.UniqueConstraint(fields=["adapter_key", "account"],
                                    name="circuit_breaker_unique_pair"),
        ]

    def __str__(self) -> str:
        return f"{self.adapter_key}/{self.account_id} {self.state}"
