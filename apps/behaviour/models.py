"""Stanje persone, rutine i svetski događaji. Canon v1.1 §1, §4, §11.1–11.2.

Odstupanja od Database & Django Schema v0.1 (Canon §0 — Canon ima prvenstvo):

  - App nosi britansko pisanje imena — `behaviour` (Canon §1, §0.3).
  - `TraitProfile` NIJE ovde. Canon §1 daje vlasništvo nad njim app-u
    `personas`, zajedno sa `VoiceProfile` — osobina je deo identiteta,
    stanje je deo ponašanja.
  - `WorldEvent` JESTE ovde. Šema ga je stavila uz planove i akcije;
    Canon §1 ga daje `behaviour`-u jer događaj menja stanje, a plan je
    posledica stanja.
  - `BehaviourState` je prepisan po Canon §4.2. Šema je imala šest polja
    (`mood` i još pet, videti §4.2); Canon ima osamnaest i izričito ukida
    stara imena. `valence` je jedino polje sa negativnim opsegom, jer
    jednodimenzionalni „mood" ne razlikuje mirno zadovoljstvo od uzbuđenja.
  - `StateDelta` je NOVO (Canon §1, §4.3). Bez njega se ne može dokazati
    da je reducer deterministički, a to je preduslov za SIM_SEED
    reproducibilnost.
"""

from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common import enums as E
from common.models import JSON_DICT, UUIDModel, unit_interval

#: Canon §4.2 — polja stanja u opsegu 0.000–1.000. `valence` nije među njima.
_UNIT_STATES: tuple[str, ...] = (
    "energy",
    "arousal",
    "cognitive_load",
    "social_appetite",
    "curiosity_now",
    "focus",
    "novelty_need",
    "stress",
    "content_pressure",
    "inbox_pressure",
    "topic_saturation",
    "risk_alert",
)


def _unit_checks(prefix: str, fields: tuple[str, ...]) -> list[models.CheckConstraint]:
    """CHECK po polju umesto jednog složenog — da poruka o kršenju imenuje polje."""
    return [
        models.CheckConstraint(
            condition=models.Q(**{f"{f}__gte": 0}) & models.Q(**{f"{f}__lte": 1}),
            name=f"{prefix}_{f}_unit",
        )
        for f in fields
    ]


class BehaviourState(models.Model):
    """Jedan red po personi. Canon §4.2 — osamnaest kanonskih polja.

    `state_version` je obavezan: Canon §11.1 zabranjuje „last write wins".
    Worker radi `UPDATE … WHERE persona_id=? AND state_version=?` i na nula
    pogođenih redova mora ponovo da učita stanje, a ne da prepiše tuđe.
    """

    persona = models.OneToOneField(
        "personas.Persona",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="behaviour_state",
    )

    # --- afektivno stanje (Canon §4.1–4.2)
    energy = unit_interval()
    valence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        validators=[MinValueValidator(-1), MaxValueValidator(1)],
        help_text="−1.000 do 1.000. Prikaz: (valence + 1) / 2 — izvedeno, ne polje.",
    )
    arousal = unit_interval()

    # --- kapacitet i sklonost
    cognitive_load = unit_interval()
    social_appetite = unit_interval()
    curiosity_now = unit_interval(
        help_text="Trenutna radoznalost; trajna osobina je TraitProfile.curiosity."
    )
    focus = unit_interval()
    novelty_need = unit_interval()
    stress = unit_interval()

    # --- pritisci iz okruženja
    content_pressure = unit_interval()
    inbox_pressure = unit_interval()
    topic_saturation = unit_interval()
    risk_alert = unit_interval()

    # --- raspoloživost
    free_minutes = models.SmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(1440)]
    )
    attention_remaining = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(24)],
        help_text="Jedinice pažnje, ne minuti.",
    )

    # --- buđenje (Canon §11.2)
    next_wake_at = models.DateTimeField(null=True, blank=True)
    wake_priority = models.SmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Brojčana vrednost iz WAKE_PRIORITY_VALUE (Canon §11.2).",
    )

    state_version = models.PositiveIntegerField(default=1)
    last_state_event_at = models.DateTimeField(null=True, blank=True)
    state_ext = JSON_DICT(help_text="Canon §5 — *_ext obrazac, uz JSON Schema.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "behaviour_state"
        indexes = [
            # Scheduler čita samo ovaj indeks svakih 30 s (Canon §11.1).
            models.Index(fields=["next_wake_at", "wake_priority"]),
        ]
        constraints = [
            *_unit_checks("state", _UNIT_STATES),
            models.CheckConstraint(
                condition=models.Q(valence__gte=-1) & models.Q(valence__lte=1),
                name="state_valence_signed_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(free_minutes__gte=0)
                & models.Q(free_minutes__lte=1440),
                name="state_free_minutes_range",
            ),
            models.CheckConstraint(
                condition=models.Q(attention_remaining__gte=0)
                & models.Q(attention_remaining__lte=24),
                name="state_attention_range",
            ),
            models.CheckConstraint(
                condition=models.Q(wake_priority__gte=0)
                & models.Q(wake_priority__lte=100),
                name="state_wake_priority_range",
            ),
        ]

    def __str__(self) -> str:
        return f"state<{self.persona_id}> v{self.state_version}"


class StateDelta(UUIDModel):
    """Append-only trag jedne primene reducera. Canon §4.3.

    `new_state = reduce(previous_state, event, context)` — isti ulaz uvek daje
    isti izlaz. Ova tabela je jedini način da se to dokaže na produkcijskim
    podacima: čuva se ulazna verzija, ključ reducera i tačno šta se promenilo.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="state_deltas"
    )
    world_event = models.ForeignKey(
        "behaviour.WorldEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="state_deltas",
    )
    run = models.ForeignKey(
        "orchestration.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="state_deltas",
    )
    reducer_key = models.CharField(max_length=120)
    from_version = models.PositiveIntegerField()
    to_version = models.PositiveIntegerField()
    changes = JSON_DICT(help_text='{"stress": [0.310, 0.480]} — pre i posle.')
    occurred_at = models.DateTimeField()
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "behaviour_state_delta"
        indexes = [
            models.Index(fields=["persona", "occurred_at"]),
            models.Index(fields=["reducer_key", "occurred_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "to_version"], name="state_delta_unique_version"
            ),
            models.CheckConstraint(
                condition=models.Q(to_version__gt=models.F("from_version")),
                name="state_delta_version_advances",
            ),
        ]


class WorldEvent(UUIDModel):
    """Spoljašnji ili sintetički događaj koji može probuditi personu.

    Canon §1 ga smešta u `behaviour`: događaj ulazi u reducer i menja stanje;
    plan i akcija su tek posledica. Šema v0.1 ga je vodila uz planove.
    """

    public_id = models.CharField(max_length=32, unique=True)  # EVT- + ULID
    event_type = models.CharField(max_length=80)
    scope = models.CharField(max_length=24, choices=E.ScopeKind.choices())
    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="world_events",
        help_text="NULL za globalne i kohortne događaje.",
    )
    occurred_at = models.DateTimeField()
    available_at = models.DateTimeField(
        help_text="Pre ovog trenutka scheduler događaj ne vidi (Canon §11.1)."
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    wake_priority = models.CharField(
        max_length=32, choices=E.WakePriority.choices(), null=True, blank=True
    )
    priority = models.SmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    provenance = models.CharField(
        max_length=24,
        choices=E.Provenance.choices(),
        default=E.Provenance.OBSERVED,
    )
    payload = JSON_DICT()
    dedupe_key = models.CharField(max_length=220, null=True, blank=True)
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "behaviour_world_event"
        indexes = [
            models.Index(fields=["available_at", "priority"]),
            models.Index(fields=["persona", "available_at"]),
            models.Index(fields=["event_type", "occurred_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=models.Q(dedupe_key__isnull=False),
                name="world_event_unique_dedupe_key",
            ),
            models.CheckConstraint(
                # Događaj vezan za personu ne sme imati globalni domet i obrnuto.
                condition=(
                    models.Q(scope=E.ScopeKind.PERSONA.value, persona__isnull=False)
                    | ~models.Q(scope=E.ScopeKind.PERSONA.value)
                ),
                name="world_event_persona_scope_has_persona",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} {self.event_type}"


class RoutineTemplate(UUIDModel):
    """Weekday, weekend, travel-day. `day_mask` je bitmaska sedam dana."""

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="routine_templates"
    )
    name = models.CharField(max_length=100)
    day_mask = models.SmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(127)],
        help_text="Bit 0 = ponedeljak … bit 6 = nedelja.",
    )
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)
    priority = models.SmallIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "behaviour_routine_template"
        indexes = [models.Index(fields=["persona", "is_enabled"])]
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "name"], name="routine_template_unique_name"
            ),
            models.CheckConstraint(
                condition=models.Q(day_mask__gte=0) & models.Q(day_mask__lte=127),
                name="routine_template_day_mask_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.persona_id})"


class RoutineWindow(UUIDModel):
    """Verovatnoća i granice jedne kategorije aktivnosti unutar šablona.

    Vreme je LOKALNO za personu — jedino mesto u sistemu gde lokalno vreme
    postoji (Canon §4.2, §7.1: sve ostalo je UTC).
    """

    template = models.ForeignKey(
        RoutineTemplate, on_delete=models.CASCADE, related_name="windows"
    )
    activity_type = models.CharField(max_length=64)  # work/read/social/post/rest
    start_local = models.TimeField()
    end_local = models.TimeField()
    probability = unit_interval()
    min_minutes = models.SmallIntegerField(null=True, blank=True)
    max_minutes = models.SmallIntegerField(null=True, blank=True)
    constraints_json = JSON_DICT()

    class Meta:
        db_table = "behaviour_routine_window"
        indexes = [models.Index(fields=["template", "start_local"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(probability__gte=0) & models.Q(probability__lte=1),
                name="routine_window_probability_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(start_local__lt=models.F("end_local")),
                name="routine_window_start_before_end",
            ),
            models.CheckConstraint(
                condition=models.Q(min_minutes__isnull=True)
                | models.Q(max_minutes__isnull=True)
                | models.Q(min_minutes__lte=models.F("max_minutes")),
                name="routine_window_minutes_ordered",
            ),
        ]
