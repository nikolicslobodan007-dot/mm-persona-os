"""Pravila, odluke, odobrenja i poverenje. Canon v1.1 §1, §9, §15, §12.4–12.5.

> Planner predlaže. Policy odlučuje. Approval potvrđuje. Action Gateway
> jedini izvršava. (Canon §9.1)

Odstupanja od Database & Django Schema v0.1 (Canon §0 — Canon ima prvenstvo):

  - Tabela evaluacije iz šeme postaje `PolicyDecision` (Canon §1, §6.2).
    Ime nije
    kozmetika: evaluacija je radnja, odluka je zapis na koji se akcija
    poziva i bez kog ne sme da se izvrši. `Action.policy_decision_id`
    pokazuje ovde.
  - `PolicyDecision` dobija `public_id` (`POL-` + ULID, Canon §2.2) jer
    ulazi u izvršni ugovor (§12.6) i u razgovor sa operatorom.
  - Dodati `CapabilityGrant`, `TrustState`, `KillSwitch` i `PolicyIncident`
    (Canon §1). Šema nije imala nijedan od njih, pa §9.5 (trust matrica),
    §9.6 (kill-switch) i §12.5 (circuit breaker) nisu imali gde da žive.
  - `ApprovalRequest` dobija `approval_class` i `payload_hash` (Canon §15.2–15.3).
    Odobrava se SADRŽAJ, ne akcija: izmena posle odobrenja pravi novi hash
    i poništava odobrenje — i kod `APPROVED_WITH_CHANGES`.
  - Efekat ograničenja brzine iz šeme ne postoji pod tim imenom;
    Canon §3.5 ima `THROTTLE`.
"""

from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common import enums as E
from common.models import JSON_DICT, JSON_LIST, UUIDModel, risk_score_field

#: Canon §15.2 — statusi u kojima ljudska odluka mora imati vreme i potpis.
_DECIDED_STATUSES: tuple[str, ...] = (
    E.ApprovalStatus.APPROVED.value,
    E.ApprovalStatus.APPROVED_WITH_CHANGES.value,
    E.ApprovalStatus.REJECTED.value,
    E.ApprovalStatus.REVOKED.value,
)


class PolicyRule(UUIDModel):
    """Versionirano pravilo koje evaluator čita deterministički.

    Pravilo se nikada ne menja u mestu — nova verzija je novi red. To je
    jedini način da se odluka od pre mesec dana može ponovo objasniti
    pravilom koje je tada važilo.
    """

    key = models.CharField(max_length=120)
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=180)
    scope = models.CharField(max_length=24, choices=E.ScopeKind.choices())
    channel_type = models.CharField(
        max_length=24, choices=E.ChannelType.choices(), null=True, blank=True
    )
    action_type = models.CharField(max_length=64, blank=True)
    capability = models.CharField(max_length=64, blank=True)
    effect = models.CharField(max_length=24, choices=E.PolicyEffect.choices())
    approval_class = models.CharField(
        max_length=4, choices=E.ApprovalClass.choices(), null=True, blank=True
    )
    condition_json = JSON_DICT(help_text="DSL uslov; prazan objekat = uvek tačno.")
    rate_limit_json = JSON_DICT(help_text="Canon §9.3 — pilot limiti.")
    risk_delta = models.SmallIntegerField(
        default=0,
        validators=[MinValueValidator(-100), MaxValueValidator(100)],
        help_text="Doprinos formuli iz §9.2; težine su u policy/risk_weights.yaml.",
    )
    is_hard_prohibition = models.BooleanField(
        default=False,
        help_text=(
            "Canon §9.4 — tvrde zabrane nisu pravila koja se mogu isključiti. "
            "Red sa True postoji radi traga i reason_code-a, ne radi konfiguracije."
        ),
    )
    is_enabled = models.BooleanField(default=True)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    policy_ext = JSON_DICT()

    class Meta:
        db_table = "policy_rule"
        indexes = [
            models.Index(fields=["is_enabled", "effective_from"]),
            models.Index(fields=["channel_type", "action_type"]),
            models.Index(fields=["scope", "is_enabled"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["key", "version"], name="policy_rule_unique_version"
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="policy_rule_period_ordered",
            ),
            models.CheckConstraint(
                # REQUIRE_APPROVAL bez klase nema TTL, pa ni efekat isteka (§15.2).
                condition=~models.Q(effect=E.PolicyEffect.REQUIRE_APPROVAL.value)
                | models.Q(approval_class__isnull=False),
                name="policy_rule_approval_needs_class",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.key} v{self.version} → {self.effect}"


class PolicyDecision(UUIDModel):
    """Append-only odluka o jednoj akciji. Canon §6.2, §9.

    Nijedan spoljašnji efekat ne sme nastati bez važeće odluke referencirane
    na akciju. Zato ovde stoji i `fail_closed`: ako policy servis nije
    odgovorio u roku (`POLICY_EVAL_TIMEOUT_SECONDS`), upisuje se DENY sa
    `fail_closed=True` — odsustvo odgovora nikada nije dozvola (§12.4).
    """

    public_id = models.CharField(max_length=32, unique=True)  # POL- + ULID
    action = models.ForeignKey(
        "orchestration.Action", on_delete=models.CASCADE, related_name="decisions"
    )
    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="policy_decisions"
    )
    effect = models.CharField(max_length=24, choices=E.PolicyEffect.choices())
    risk_score = risk_score_field()
    risk_class = models.CharField(max_length=16, choices=E.RiskClass.choices())
    risk_components = JSON_DICT(
        help_text="Canon §9.2 — svaki sabirak posebno, radi objašnjivosti."
    )
    matched_rules = JSON_LIST(help_text='[{"key": "…", "version": 3, "effect": "…"}]')
    decisive_rule = models.ForeignKey(
        PolicyRule,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decisions",
    )
    reason_code = models.CharField(max_length=64, blank=True)
    reason = models.TextField()
    approval_class = models.CharField(
        max_length=4, choices=E.ApprovalClass.choices(), null=True, blank=True
    )
    fail_closed = models.BooleanField(default=False)
    evaluator_version = models.CharField(max_length=40, blank=True)
    context_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField()
    eval_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    trace_id = models.UUIDField(null=True, blank=True)

    # --- F5 (ADR-0007): Canon §8.4 kanonski odgovor
    policy_version = models.CharField(max_length=40, blank=True)
    reason_codes = JSON_LIST(help_text="Svi razlozi; prvi je odlučujući (`reason_code`).")
    obligations = JSON_LIST(help_text="Šta gateway mora da proveri pre izvršenja.")
    constraints = JSON_DICT()
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Posle ovoga odluka ne važi i gateway traži novu evaluaciju.",
    )

    class Meta:
        db_table = "policy_decision"
        indexes = [
            models.Index(fields=["action", "evaluated_at"]),
            models.Index(fields=["effect", "evaluated_at"]),
            models.Index(fields=["persona", "evaluated_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(risk_score__gte=0) & models.Q(risk_score__lte=100),
                name="policy_decision_risk_range",
            ),
            models.CheckConstraint(
                # Zona se ne upisuje (§3.7), ali klasa odobrenja mora pratiti efekat.
                condition=~models.Q(effect=E.PolicyEffect.REQUIRE_APPROVAL.value)
                | models.Q(approval_class__isnull=False),
                name="policy_decision_approval_needs_class",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} {self.effect} ({self.risk_score})"

    @property
    def zone(self) -> E.Zone:
        """Canon §3.7 — IZVEDENA oznaka. Postoji kao svojstvo, nikada kao kolona."""
        return E.EFFECT_TO_ZONE[E.PolicyEffect(self.effect)]


class ApprovalRequest(UUIDModel):
    """Ljudska potvrda za akciju koju je policy označio. Canon §15.2–15.3.

    `payload_hash` je srce ovog modela: odobrava se sadržaj. U trenutku
    izvršenja gateway poredi `payload_hash` sa `Action.content_hash` i
    odbija izvršenje ako se razlikuju — uključujući slučaj kada je izmenu
    napravio sam odobravalac (`APPROVED_WITH_CHANGES`).
    """

    public_id = models.CharField(max_length=32, unique=True)  # APR- + ULID
    action = models.ForeignKey(
        "orchestration.Action", on_delete=models.CASCADE, related_name="approvals"
    )
    decision = models.ForeignKey(
        PolicyDecision,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approvals",
    )
    approval_class = models.CharField(max_length=4, choices=E.ApprovalClass.choices())
    status = models.CharField(
        max_length=24,
        choices=E.ApprovalStatus.choices(),
        default=E.ApprovalStatus.PENDING,
    )
    payload_hash = models.CharField(max_length=64)
    requested_by = models.CharField(max_length=120)  # system/persona/service
    assigned_to = models.CharField(max_length=180, blank=True)
    reason = models.TextField()
    expires_at = models.DateTimeField(
        help_text="Canon §15.2 — TTL po klasi; prenosi se kao approval_expires_at."
    )
    expiry_effect = models.CharField(
        max_length=40, help_text="Canon §15.2 — APPROVAL_EXPIRY_EFFECT."
    )
    decided_by = models.CharField(max_length=180, blank=True)
    decided_role = models.CharField(
        max_length=24, choices=E.Role.choices(), null=True, blank=True
    )
    decision_note = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "policy_approval_request"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["action", "status"]),
            models.Index(fields=["expires_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(status__in=_DECIDED_STATUSES)
                | models.Q(decided_at__isnull=False),
                name="approval_decided_has_timestamp",
            ),
            models.CheckConstraint(
                condition=~models.Q(status__in=_DECIDED_STATUSES)
                | ~models.Q(decided_by=""),
                name="approval_decided_has_decider",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} {self.approval_class} {self.status}"


class CapabilityGrant(UUIDModel):
    """Izričita dodela jedne sposobnosti jednoj personi. Canon §6.4, §9.5, §15.2.

    Odvojeno od `TrustState`: grant je administrativni akt sa dokazom i
    rokom (A3 odobrenje), `TrustState` je trenutno stanje koje sistem sme
    sam da spusti posle prekršaja. Brisanje grant-a i automatski pad nisu
    ista stvar i ne smeju deliti red.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="capability_grants"
    )
    capability = models.CharField(max_length=64)
    min_trust_level = models.CharField(max_length=4, choices=E.TrustLevel.choices())
    channel_account = models.ForeignKey(
        "channels.ChannelAccount",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="capability_grants",
        help_text="NULL = važi za sve naloge persone.",
    )
    granted_by = models.CharField(max_length=180)
    granted_at = models.DateTimeField()
    approval = models.ForeignKey(
        ApprovalRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="capability_grants",
    )
    evidence_ref = models.CharField(max_length=512, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.TextField(blank=True)

    class Meta:
        db_table = "policy_capability_grant"
        indexes = [
            models.Index(fields=["persona", "capability"]),
            models.Index(fields=["expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "capability", "channel_account"],
                condition=models.Q(revoked_at__isnull=True),
                name="capability_grant_unique_active",
            ),
            models.CheckConstraint(
                # Canon §3.11 (A-08) — L3/L4 se ne mogu dodeliti ni ovde.
                condition=models.Q(
                    min_trust_level__in=E.ASSIGNABLE_TRUST_LEVEL_VALUES
                ),
                name="capability_grant_trust_assignable",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.persona_id}:{self.capability}@{self.min_trust_level}"


class TrustState(UUIDModel):
    """`(persona, capability) → level`. Canon §9.5.

    Jedan `CRITICAL` prekršaj → trenutni pad na `L0` za tu sposobnost, i
    `SUSPENDED` za personu ako je prekršaj iz §9.4. `auto_downgrade_count`
    je brojač koji se ne resetuje sam — rast tog broja je signal da
    konfiguracija persone, a ne pojedinačna akcija, nije u redu.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="trust_states"
    )
    capability = models.CharField(max_length=64)
    level = models.CharField(
        max_length=4, choices=E.TrustLevel.choices(), default=E.TrustLevel.L0
    )
    granted_at = models.DateTimeField()
    evidence_ref = models.CharField(max_length=512, blank=True)
    auto_downgrade_count = models.PositiveSmallIntegerField(default=0)
    last_downgrade_at = models.DateTimeField(null=True, blank=True)
    last_incident = models.ForeignKey(
        "policy.PolicyIncident",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trust_states",
    )
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "policy_trust_state"
        indexes = [models.Index(fields=["persona", "level"])]
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "capability"], name="trust_state_unique_pair"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    level__in=E.ASSIGNABLE_TRUST_LEVEL_VALUES
                ),
                name="trust_state_level_assignable",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.persona_id}:{self.capability}={self.level}"


class KillSwitch(UUIDModel):
    """Zaustavljanje izvršenja po hijerarhiji GLOBAL → … → ACCOUNT. Canon §9.6.

    Merilo nije vreme odgovora API-ja nego vreme do poslednjeg zaustavljenog
    worker-a: globalni stop mora zaustaviti sve za manje od 30 sekundi, i to
    je jedan od automatskih NO-GO uslova pilota (§16.4).
    """

    scope = models.CharField(max_length=24, choices=E.KillSwitchScope.choices())
    target_ref = models.CharField(
        max_length=220,
        blank=True,
        help_text="Prazno za GLOBAL; inače persona/kanal/capability/nalog.",
    )
    is_active = models.BooleanField(default=True)
    reason = models.TextField()
    activated_by = models.CharField(max_length=180)
    activated_at = models.DateTimeField()
    released_by = models.CharField(max_length=180, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    stopped_workers = models.PositiveIntegerField(null=True, blank=True)
    stop_latency_ms = models.PositiveIntegerField(
        null=True, blank=True, help_text="Do poslednjeg zaustavljenog worker-a."
    )
    incident = models.ForeignKey(
        "policy.PolicyIncident",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kill_switches",
    )

    class Meta:
        db_table = "policy_kill_switch"
        indexes = [
            models.Index(fields=["is_active", "scope"]),
            models.Index(fields=["activated_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "target_ref"],
                condition=models.Q(is_active=True),
                name="kill_switch_unique_active_target",
            ),
            models.CheckConstraint(
                condition=~models.Q(scope=E.KillSwitchScope.GLOBAL.value)
                | models.Q(target_ref=""),
                name="kill_switch_global_has_no_target",
            ),
            models.CheckConstraint(
                condition=models.Q(is_active=True, released_at__isnull=True)
                | models.Q(is_active=False),
                name="kill_switch_active_not_released",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.target_ref or '*'} {'ON' if self.is_active else 'off'}"


class PolicyIncident(UUIDModel):
    """Incident sa `public_id` oblika `INC-20260918-001`. Canon §2.2, §9.4, §12.5.

    Otvara ga sistem, ne čovek: tvrda zabrana iz §9.4 dodirnuta iz planner-a
    → `SEV1`; otvoren circuit breaker → `SEV3` (§12.5). `MTTD < 5 min` iz
    §16.5 meri se razlikom `detected_at − occurred_at`.
    """

    public_id = models.CharField(max_length=24, unique=True)  # INC-YYYYMMDD-NNN
    severity = models.CharField(max_length=8, choices=E.IncidentSeverity.choices())
    status = models.CharField(
        max_length=24, choices=E.IncidentStatus.choices(), default=E.IncidentStatus.OPEN
    )
    incident_kind = models.CharField(max_length=80)
    title = models.CharField(max_length=220)
    summary = models.TextField(blank=True)

    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )
    action = models.ForeignKey(
        "orchestration.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )
    decision = models.ForeignKey(
        PolicyDecision,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )
    channel_account = models.ForeignKey(
        "channels.ChannelAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )

    occurred_at = models.DateTimeField()
    detected_at = models.DateTimeField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    mitigated_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    owner = models.CharField(max_length=180, blank=True)
    timeline = JSON_LIST()
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "policy_incident"
        indexes = [
            models.Index(fields=["status", "severity", "detected_at"]),
            models.Index(fields=["persona", "detected_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(detected_at__gte=models.F("occurred_at")),
                name="incident_detected_after_occurred",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=E.IncidentStatus.CLOSED.value)
                | models.Q(closed_at__isnull=False),
                name="incident_closed_has_timestamp",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} {self.severity} {self.title}"
