"""Ideje, sadržaj, prilozi i objave. Canon v1.1 §1, §3.6, §15.3.

Odstupanja od Database & Django Schema v0.1 (Canon §0 — Canon ima prvenstvo):

  - `risk_level` (GREEN/YELLOW/RED) je UKLONJEN sa `ContentItem`, isto kao
    sa `Action`. Canon §3.6–3.7: `risk_score` je ceo broj 0–100 i svojstvo
    zahteva, zona je izvedena iz odluke i nikada se ne upisuje.
  - `content_type` → `format` sa enum-om `ContentFormat`. Ime `content_type`
    se u Django-u sudara sa `django.contrib.contenttypes`, što je dovoljan
    razlog samo po sebi.
  - Dodat je `content_hash` (Canon §15.3): odobrava se sadržaj, ne akcija.
    Svaka izmena posle odobrenja pravi novi hash i poništava odobrenje.
  - `Publication` dobija vezu na `Action` — bez nje objava postoji u bazi
    bez policy traga, a Canon §6.2 to zabranjuje kao klasu.
  - `source_event` pokazuje na `behaviour.WorldEvent` (Canon §1), ne na
    `orchestration.WorldEvent` kako je stajalo u šemi.
"""

from __future__ import annotations

from django.db import models

from common import enums as E
from common.models import JSON_DICT, JSON_LIST, UUIDModel, risk_score_field


class ContentIdea(UUIDModel):
    """Ideja pre izrade drafta. Jeftin red — nastaje u desetinama dnevno."""

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="content_ideas"
    )
    topic = models.CharField(max_length=220)
    angle = models.TextField(blank=True)
    priority = models.SmallIntegerField(default=0)
    source_event = models.ForeignKey(
        "behaviour.WorldEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_ideas",
    )
    source_memory = models.ForeignKey(
        "memory.MemoryItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_ideas",
    )
    status = models.CharField(
        max_length=16, choices=E.IdeaStatus.choices(), default=E.IdeaStatus.OPEN
    )
    dedupe_key = models.CharField(
        max_length=220,
        null=True,
        blank=True,
        help_text="Canon §16.3 — ponavljanje sadržaja < 0,20 je kapija pilota.",
    )

    class Meta:
        db_table = "content_idea"
        indexes = [models.Index(fields=["persona", "status", "priority"])]
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "dedupe_key"],
                condition=models.Q(dedupe_key__isnull=False),
                name="content_idea_unique_dedupe",
            )
        ]

    def __str__(self) -> str:
        return f"{self.topic[:48]} ({self.status})"


class ContentItem(UUIDModel):
    """Jedan logički komad sadržaja, nezavisan od kanala.

    Razdvajanje sadržaja od objave je namerno: isti tekst može otići na
    LinkedIn Page i u newsletter, sa različitim ishodom i različitim
    provider ID-jem, ali sa istim `content_hash`-om i istim odobrenjem.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="content_items"
    )
    idea = models.ForeignKey(
        ContentIdea,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
    )
    format = models.CharField(max_length=24, choices=E.ContentFormat.choices())
    title = models.CharField(max_length=220, blank=True)
    body = models.TextField()
    language = models.CharField(max_length=16)
    status = models.CharField(
        max_length=24, choices=E.ContentStatus.choices(), default=E.ContentStatus.DRAFT
    )

    # Canon §3.6 — svojstvo zahteva; zona se ne upisuje.
    risk_score = risk_score_field(default=0)
    risk_class = models.CharField(
        max_length=16, choices=E.RiskClass.choices(), default=E.RiskClass.LOW
    )

    content_hash = models.CharField(
        max_length=64, blank=True, help_text="Canon §15.3 — osnov odobrenja."
    )
    provenance = models.CharField(
        max_length=24, choices=E.Provenance.choices(), default=E.Provenance.GENERATED
    )
    disclosure_included = models.BooleanField(
        default=False, help_text="Canon §9.4 tačka 2 — AI priroda se ne skriva."
    )
    citations = JSON_LIST(help_text="Canon §10.4 — izvori tvrdnji, radi provere.")
    version = models.PositiveIntegerField(default=1)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    # F7 (ADR-0009): koje buđenje je napravilo nacrt i zašto je stao.
    run = models.ForeignKey(
        "orchestration.AgentRun", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="content_items",
    )
    status_reason = models.CharField(max_length=80, blank=True)

    class Meta:
        db_table = "content_item"
        indexes = [
            models.Index(fields=["persona", "status", "scheduled_for"]),
            models.Index(fields=["risk_class", "status"]),
            models.Index(fields=["content_hash"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(risk_score__gte=0) & models.Q(risk_score__lte=100),
                name="content_item_risk_score_range",
            ),
            models.CheckConstraint(
                # Ne sme se zakazati ono što nije odobreno (Canon §15.3).
                condition=~models.Q(status=E.ContentStatus.SCHEDULED.value)
                | models.Q(scheduled_for__isnull=False),
                name="content_item_scheduled_has_time",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.format}:{self.title or self.body[:40]}"


class ContentAsset(UUIDModel):
    """Veza sadržaja i medijskog fajla, sa ulogom i redosledom."""

    content = models.ForeignKey(
        ContentItem, on_delete=models.CASCADE, related_name="assets"
    )
    asset = models.ForeignKey(
        "visuals.MediaAsset", on_delete=models.CASCADE, related_name="content_links"
    )
    role = models.CharField(max_length=16, choices=E.AssetRole.choices())
    position = models.SmallIntegerField(default=0)
    alt_text = models.CharField(max_length=420, blank=True)

    class Meta:
        db_table = "content_asset"
        constraints = [
            models.UniqueConstraint(
                fields=["content", "asset", "role"], name="content_asset_unique"
            ),
            models.UniqueConstraint(
                fields=["content", "role", "position"],
                name="content_asset_unique_position",
            ),
        ]
        indexes = [models.Index(fields=["content", "position"])]


class Publication(UUIDModel):
    """Kanal-specifična objava i provider ID.

    `action` nije opciono iz udobnosti: objava bez akcije je objava bez
    policy odluke, a Canon §6.2 to zabranjuje. Jedini razlog za NULL je
    istorijski uvoz, pa polje ostaje nullable uz CHECK koji traži akciju
    za sve što je stvarno objavljeno.
    """

    content = models.ForeignKey(
        ContentItem, on_delete=models.CASCADE, related_name="publications"
    )
    channel_account = models.ForeignKey(
        "channels.ChannelAccount", on_delete=models.PROTECT, related_name="publications"
    )
    action = models.ForeignKey(
        "orchestration.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publications",
    )
    status = models.CharField(
        max_length=16,
        choices=E.PublicationStatus.choices(),
        default=E.PublicationStatus.SCHEDULED,
    )
    provider_post_id = models.CharField(max_length=220, null=True, blank=True)
    public_url = models.TextField(blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    retracted_at = models.DateTimeField(null=True, blank=True)
    provider_payload = JSON_DICT(help_text="Sanitizovano — bez tajni (Canon §17).")
    error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        db_table = "content_publication"
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["channel_account", "published_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["channel_account", "provider_post_id"],
                condition=models.Q(provider_post_id__isnull=False),
                name="publication_unique_provider_post",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=E.PublicationStatus.PUBLISHED.value)
                | models.Q(published_at__isnull=False),
                name="publication_published_has_timestamp",
            ),
            models.CheckConstraint(
                # Canon §6.2 — objavljeno bez akcije znači objavljeno bez odluke.
                condition=~models.Q(status=E.PublicationStatus.PUBLISHED.value)
                | models.Q(action__isnull=False),
                name="publication_published_has_action",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.channel_account_id}:{self.provider_post_id or self.status}"


class EditorialLesson(UUIDModel):
    """Pouka iz odluke urednika — odbijanje sa razlogom ili izmena teksta (ADR-0014).

    `persona` prazna = pouka važi za SVE persone (kućni stil organizacije).
    Nije memorija: ne bledi, ne takmiči se u retrieval-u, nego ide u svaki
    prompt za pisanje dok je aktivna. Urednik je gasi kad više ne važi.
    """

    persona = models.ForeignKey(
        "personas.Persona", null=True, blank=True, on_delete=models.CASCADE,
        related_name="editorial_lessons",
        help_text="Prazno = važi za sve persone (ili za ceo sektor, ako je on popunjen).")
    department = models.ForeignKey(
        "personas.Department", null=True, blank=True, on_delete=models.CASCADE,
        related_name="editorial_lessons",
        help_text="Popunjeno = pouka važi za sve u tom sektoru (ADR-0017).")
    kind = models.CharField(max_length=16, help_text="rejected | edited | manual")
    text = models.CharField(max_length=500, help_text="Pravilo, kako ga model čita.")
    example_before = models.CharField(max_length=300, blank=True)
    example_after = models.CharField(max_length=300, blank=True)
    source_action = models.ForeignKey(
        "orchestration.Action", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+")
    created_by = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["persona", "is_active", "created_at"]),
                   models.Index(fields=["department", "is_active", "created_at"])]
        constraints = [
            models.CheckConstraint(
                # Pouka ima tačno jedan domet: agent, sektor ili cela firma.
                condition=~(models.Q(persona__isnull=False)
                            & models.Q(department__isnull=False)),
                name="lesson_single_scope",
            )
        ]

    def __str__(self) -> str:
        who = self.persona_id or self.department_id or "SVI"
        return f"{who}: {self.text[:60]}"

