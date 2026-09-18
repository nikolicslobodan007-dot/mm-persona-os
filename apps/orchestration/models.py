"""Ciklusi, planovi, akcije i pokušaji. Canon v1.1 §1, §2.2, §6, §12.

Odstupanja od Database & Django Schema v0.1 (Canon §0 — Canon ima prvenstvo):

  - `WorldEvent` NIJE ovde. Canon §1 ga daje app-u `behaviour`: događaj
    menja stanje, a plan je posledica stanja. Veze se drže preko stringa.
  - Dodat je `AgentRun` (Canon §6.1) — jedno buđenje persone. Šema ga nije
    imala, pa se plan nije mogao vezati za ciklus ni trošak za buđenje.
  - Dodat je `ActionAttempt` (Canon §6.1, §3.9). `ExecutionOutcome` opisuje
    JEDAN pokušaj i ne sme da živi na `Action`: inače bi `UNKNOWN_EFFECT`
    bio prepisan sledećim pokušajem, a to je upravo ishod koji nikada ne
    sme voditi u retry bez reconcile-a (§12.3).
  - `risk_level` (GREEN/YELLOW/RED) je UKLONJEN sa `Action`. Canon §3.6–3.7
    razdvaja tri stvari koje je šema spajala: `risk_score` je ceo broj
    0–100 i svojstvo ZAHTEVA, `PolicyEffect` je ODLUKA, a zona je IZVEDENA
    oznaka koja se nikada ne upisuje u bazu.
  - Dodat je `policy_decision` sa CHECK ograničenjem (Canon §6.2). Ovo je
    hard KPI pilota — `actions_without_policy_decision = 0` (§16.5) — i
    Canon izričito traži da bude sprovedeno na nivou baze, a ne u servisu.
  - Dodat je `content_hash` (Canon §15.3): odobrava se SADRŽAJ, ne akcija.
    Izmena posle odobrenja pravi novi hash i poništava odobrenje.
"""

from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common import enums as E
from common.models import JSON_DICT, UUIDModel, risk_score_field

#: Canon §6.2 — statusi u kojima akcija već sme da dodirne spoljni svet.
#: Od `QUEUED` nadalje `policy_decision` mora postojati.
_REQUIRES_DECISION: tuple[str, ...] = (
    E.ActionStatus.QUEUED.value,
    E.ActionStatus.RUNNING.value,
    E.ActionStatus.RETRY_WAIT.value,
    E.ActionStatus.SUCCEEDED.value,
)


class AgentRun(UUIDModel):
    """Jedno buđenje persone. Canon §6.1, §11.2.

    Nosi `trace_id` celog ciklusa i zbir troška; svaki event u sistemu
    nosi `run_id` osim onih iz `RUN_ID_OPTIONAL`, i ovo je tabela na
    koju taj ID pokazuje.
    """

    public_id = models.CharField(max_length=32, unique=True)  # RUN- + ULID
    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="runs"
    )
    trigger_event = models.ForeignKey(
        "behaviour.WorldEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    wake_priority = models.CharField(
        max_length=32, choices=E.WakePriority.choices(), null=True, blank=True
    )
    status = models.CharField(
        max_length=24, choices=E.RunStatus.choices(), default=E.RunStatus.RUNNING
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    prompt_hash = models.CharField(max_length=64, blank=True)
    decisions_count = models.PositiveSmallIntegerField(default=0)
    cost_eur_cents = models.BigIntegerField(
        default=0, help_text="Canon §13.1 — EUR u centima, nikada float."
    )
    trace_id = models.UUIDField(null=True, blank=True)
    summary_json = JSON_DICT()

    class Meta:
        db_table = "orchestration_agent_run"
        indexes = [
            models.Index(fields=["persona", "started_at"]),
            models.Index(fields=["status", "started_at"]),
            models.Index(fields=["trace_id"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(ended_at__gte=models.F("started_at")),
                name="agent_run_ends_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(cost_eur_cents__gte=0),
                name="agent_run_cost_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} ({self.persona_id})"


class AgentPlan(UUIDModel):
    """Skup nameravanih koraka iz jednog run-a. Canon §6.1."""

    public_id = models.CharField(max_length=32, unique=True)  # PLN- + ULID
    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="plans"
    )
    run = models.ForeignKey(
        AgentRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="plans"
    )
    trigger_event = models.ForeignKey(
        "behaviour.WorldEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plans",
    )
    goal = models.TextField()
    status = models.CharField(
        max_length=24, choices=E.PlanStatus.choices(), default=E.PlanStatus.DRAFT
    )
    priority = models.SmallIntegerField(default=0)
    valid_until = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    superseded_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
    )

    class Meta:
        db_table = "orchestration_agent_plan"
        indexes = [
            models.Index(fields=["persona", "status", "priority"]),
            models.Index(fields=["valid_until"]),
            models.Index(fields=["run"]),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} {self.status}"


class PlanStep(UUIDModel):
    """Jedan korak plana. Deterministički redosled, uz opcionu zavisnost."""

    plan = models.ForeignKey(AgentPlan, on_delete=models.CASCADE, related_name="steps")
    sequence = models.SmallIntegerField()
    step_type = models.CharField(max_length=24, choices=E.StepType.choices())
    description = models.TextField()
    depends_on = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dependents",
    )
    status = models.CharField(
        max_length=24, choices=E.StepStatus.choices(), default=E.StepStatus.PENDING
    )
    version = models.PositiveIntegerField(default=1)
    input_json = JSON_DICT()
    output_json = JSON_DICT()

    class Meta:
        db_table = "orchestration_plan_step"
        indexes = [models.Index(fields=["plan", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "sequence"], name="plan_step_unique_sequence"
            ),
            models.CheckConstraint(
                condition=~models.Q(depends_on=models.F("id")),
                name="plan_step_no_self_dependency",
            ),
        ]


class Action(UUIDModel):
    """Jedan predlog spoljašnjeg ili unutrašnjeg efekta, sa svojim policy tragom.

    Dva ograničenja na ovoj tabeli su hard KPI pilota (Canon §16.5), pa stoje
    u bazi a ne u servisnom sloju:
      - `idempotency_key` je UNIQUE NOT NULL → `duplicate_side_effects = 0`;
      - `policy_decision` mora postojati od `QUEUED` nadalje (§6.2)
        → `actions_without_policy_decision = 0`.
    """

    public_id = models.CharField(max_length=32, unique=True)  # ACT- + ULID
    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.PROTECT, related_name="actions"
    )
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actions",
    )
    plan_step = models.ForeignKey(
        PlanStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actions",
    )
    channel_account = models.ForeignKey(
        "channels.ChannelAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="actions",
    )

    action_type = models.CharField(
        max_length=64, help_text="Canon §6.4: `channel.post.create`, `mail.send`…"
    )
    capability = models.CharField(
        max_length=64,
        blank=True,
        help_text="Canon §6.4 — ključ iz `policy/capabilities.yaml`.",
    )
    status = models.CharField(
        max_length=24,
        choices=E.ActionStatus.choices(),
        default=E.ActionStatus.PROPOSED,
    )

    # Canon §3.6 — svojstvo zahteva. Zona se NE upisuje; izvodi se iz odluke.
    risk_score = risk_score_field(default=0)
    risk_class = models.CharField(
        max_length=16, choices=E.RiskClass.choices(), default=E.RiskClass.LOW
    )

    policy_decision = models.ForeignKey(
        "policy.PolicyDecision",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="actions",
        help_text="Canon §6.2 — obavezno od QUEUED nadalje.",
    )

    target_actor = models.ForeignKey(
        "social_graph.Actor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="targeted_actions",
    )
    target_ref = models.CharField(max_length=500, blank=True)
    intent = models.TextField()
    input_json = JSON_DICT()
    result_json = JSON_DICT()

    content_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="Canon §15.3 — mora odgovarati ApprovalRequest.payload_hash.",
    )
    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
        help_text="Canon §6.3 — sha256(persona|type|target|content|step), TTL ≥ 24 h.",
    )
    max_attempts = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Canon §12.6 — rok IZVRŠENJA; rok odobrenja je drugo polje.",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "orchestration_action"
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["persona", "created_at"]),
            models.Index(fields=["action_type", "risk_class", "status"]),
            models.Index(fields=["trace_id"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(risk_score__gte=0) & models.Q(risk_score__lte=100),
                name="action_risk_score_range",
            ),
            models.CheckConstraint(
                # Canon §6.2 — invarijanta izvršenja, sprovedena u bazi.
                condition=~models.Q(status__in=_REQUIRES_DECISION)
                | models.Q(policy_decision__isnull=False),
                name="action_requires_policy_decision",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} {self.action_type} {self.status}"


class ActionAttempt(UUIDModel):
    """Jedan pokušaj izvršenja jedne akcije. Canon §3.9, §6.1.

    Postoji odvojeno od `Action` zato što `ExecutionOutcome` opisuje
    pokušaj, ne akciju. Bez ove tabele bi se `UNKNOWN_EFFECT` — ishod koji
    znači „ne znamo da li je spoljašnji efekat nastao" — prepisao sledećim
    pokušajem, i izgubio bi se trag zbog kog se uopšte radi reconcile
    umesto retry-ja (§12.3).
    """

    action = models.ForeignKey(
        Action, on_delete=models.CASCADE, related_name="attempts"
    )
    attempt_number = models.PositiveSmallIntegerField()
    outcome = models.CharField(
        max_length=40, choices=E.ExecutionOutcome.choices(), null=True, blank=True
    )
    reason_code = models.CharField(
        max_length=48, blank=True, help_text="Canon §3.9 — `OUTCOME_REASON_CODE`."
    )
    evidence_level = models.CharField(
        max_length=24, choices=E.EvidenceLevel.choices(), null=True, blank=True
    )
    evidence_ref = models.CharField(
        max_length=512, blank=True, help_text="Ključ u object storage-u."
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    worker_id = models.CharField(max_length=120, blank=True)
    session = models.ForeignKey(
        "runtime.RuntimeSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attempts",
    )
    error_detail = models.TextField(blank=True)
    payload = JSON_DICT()

    class Meta:
        db_table = "orchestration_action_attempt"
        indexes = [
            models.Index(fields=["action", "attempt_number"]),
            models.Index(fields=["outcome", "started_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["action", "attempt_number"],
                name="action_attempt_unique_number",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_number__gte=1),
                name="action_attempt_number_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action_id}#{self.attempt_number} {self.outcome or 'pending'}"
