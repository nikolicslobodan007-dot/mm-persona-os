"""Memorija i znanje. Canon v1.1 §1, §10.

Odstupanja od Database & Django Schema v0.1 (Canon §0 — Canon ima prvenstvo):

  - `importance` je UKINUTO. Svuda `salience` (Canon §10.1). Ovo nije
    kozmetika: formule eligibility i retrieval iz §10.2 čitaju `salience`,
    i dva imena za istu veličinu su bila izvor neslaganja između spec-a,
    šeme i seed teksta.
  - `MemoryKind` → `MemoryType`, malim slovima, jer su vrednosti ključevi
    `MEMORY_HALF_LIFE_DAYS` i `MEMORY_LAMBDA` (Canon §3.12, §10.3).
    `RELATIONSHIP` → `social`.
  - Dodat `status` (Canon §3.13) — bez njega se PINNED memorija ne može
    izuzeti iz decay-a.
  - Dodat `provenance` (Canon §10.4) — sadržaj sa `inferred` nikada ne
    ulazi u javni izlaz kao činjenica o biografiji persone.
  - Dodati `MemorySource`, `MemoryContradiction` i `MemoryContextPack`
    (Canon §1). Šema ih nije imala; bez `MemoryContextPack` ne postoji
    zapis šta je zaista ušlo u prompt, pa se „memory precision ≥ 95%"
    iz kapija pilota (§16.3) ne može meriti na produkcijskim podacima.
  - Dimenzija vektora dolazi iz `settings.EMBEDDING_DIM` — Canon §10.5
    izričito zabranjuje hardkodovanje.
  - HNSW indeks stoji u modelu, ali Canon §10.5 traži da se u produkciji
    kreira `CONCURRENTLY` i tek posle merenja recall/latency; do tada je
    sekvencijalno pretraživanje prihvatljivo.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from pgvector.django import HnswIndex, VectorField

from common import enums as E
from common.models import JSON_DICT, JSON_LIST, UUIDModel, unit_interval


class MemoryItem(UUIDModel):
    """Osnovni memorijski zapis. Pretraga je UVEK persona-scoped (Canon §10.2)."""

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="memories"
    )
    memory_type = models.CharField(max_length=24, choices=E.MemoryType.choices())
    status = models.CharField(
        max_length=24, choices=E.MemoryStatus.choices(), default=E.MemoryStatus.ACTIVE
    )
    visibility = models.CharField(
        max_length=24,
        choices=E.MemoryVisibility.choices(),
        default=E.MemoryVisibility.PRIVATE,
    )
    provenance = models.CharField(max_length=24, choices=E.Provenance.choices())

    title = models.CharField(max_length=220, blank=True)
    content = models.TextField()

    # Canon §10.1–10.2 — ulazi u obe formule; jedno ime, jedan opseg.
    salience = unit_interval()
    confidence = unit_interval()
    goal_relevance = unit_interval(default=0)
    novelty = unit_interval(default=0)
    sensitivity = unit_interval(
        default=0, help_text="Ulazi kao sensitivity_penalty u eligibility (§10.2)."
    )

    event_time = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_recalled_at = models.DateTimeField(null=True, blank=True)
    recall_count = models.PositiveIntegerField(default=0)
    superseded_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
    )

    class Meta:
        db_table = "memory_item"
        indexes = [
            # Canon §10.2 — `persona` je prvi u svakom indeksu jer je svaka
            # pretraga ograničena na jednu personu. Zato 100M vektora nikada
            # nije jedan problem nego 10.000 malih.
            models.Index(fields=["persona", "memory_type", "created_at"]),
            models.Index(fields=["persona", "status", "expires_at"]),
            models.Index(fields=["persona", "salience"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(salience__gte=0) & models.Q(salience__lte=1),
                name="memory_salience_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=1),
                name="memory_confidence_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(goal_relevance__gte=0)
                & models.Q(goal_relevance__lte=1),
                name="memory_goal_relevance_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(novelty__gte=0) & models.Q(novelty__lte=1),
                name="memory_novelty_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(sensitivity__gte=0) & models.Q(sensitivity__lte=1),
                name="memory_sensitivity_unit",
            ),
            models.CheckConstraint(
                # SUPERSEDED bez naslednika je izgubljen zapis.
                condition=~models.Q(status=E.MemoryStatus.SUPERSEDED.value)
                | models.Q(superseded_by__isnull=False),
                name="memory_superseded_has_successor",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.memory_type}:{self.title or self.content[:40]}"


class MemorySource(UUIDModel):
    """Odakle jedna memorija potiče. Canon §10.4.

    Odvojeno od `MemoryItem.provenance`: provenance je vrsta porekla,
    ovo je konkretan trag — koji run, koja akcija, koji URL, koji
    `KnowledgeSource`. Jedna memorija sme imati više izvora; to je i
    način da se podigne `confidence` kada se ista tvrdnja potvrdi drugde.
    """

    memory = models.ForeignKey(
        MemoryItem, on_delete=models.CASCADE, related_name="sources"
    )
    source_kind = models.CharField(max_length=32, choices=E.SourceKind.choices())
    knowledge_source = models.ForeignKey(
        "memory.KnowledgeSource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_memories",
    )
    run = models.ForeignKey(
        "orchestration.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memory_sources",
    )
    action = models.ForeignKey(
        "orchestration.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memory_sources",
    )
    source_ref = models.CharField(max_length=500, blank=True)
    observed_at = models.DateTimeField()
    confidence = unit_interval(
        help_text="Polazna vrednost iz SOURCE_CONFIDENCE (Canon §10.4)."
    )

    class Meta:
        db_table = "memory_source"
        indexes = [
            models.Index(fields=["memory", "observed_at"]),
            models.Index(fields=["source_kind", "observed_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=1),
                name="memory_source_confidence_unit",
            )
        ]


class MemoryEmbedding(UUIDModel):
    """Odvojen zapis — omogućava re-embedding bez diranja same memorije."""

    memory = models.ForeignKey(
        MemoryItem, on_delete=models.CASCADE, related_name="embeddings"
    )
    model_key = models.CharField(max_length=120)
    dimensions = models.PositiveSmallIntegerField(
        help_text="Zapisano uz vektor: Canon §10.5 traži novu kolonu, ne izmenu."
    )
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM)

    class Meta:
        db_table = "memory_embedding"
        constraints = [
            models.UniqueConstraint(
                fields=["memory", "model_key"], name="memory_embedding_unique_model"
            )
        ]
        indexes = [
            HnswIndex(
                name="memory_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]


class MemoryLink(UUIDModel):
    """Veza između memorija — osnova za detekciju protivrečnosti (Canon §10.4)."""

    from_memory = models.ForeignKey(
        MemoryItem, on_delete=models.CASCADE, related_name="links_out"
    )
    to_memory = models.ForeignKey(
        MemoryItem, on_delete=models.CASCADE, related_name="links_in"
    )
    relation = models.CharField(max_length=24, choices=E.MemoryRelation.choices())
    weight = unit_interval(default=1)

    class Meta:
        db_table = "memory_link"
        constraints = [
            models.UniqueConstraint(
                fields=["from_memory", "to_memory", "relation"],
                name="memory_link_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_memory=models.F("to_memory")),
                name="memory_link_no_self",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gte=0) & models.Q(weight__lte=1),
                name="memory_link_weight_unit",
            ),
        ]


class MemoryContradiction(UUIDModel):
    """Otvorena protivrečnost između dve memorije. Canon §1, §10.4.

    Postoji kao zaseban red, a ne kao `MemoryLink(relation=contradicts)`,
    zato što protivrečnost ima svoj životni ciklus: neko je mora rešiti, i
    do rešenja obe strane moraju biti isključene iz javnog izlaza. Veza bez
    statusa to ne može da izrazi.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="contradictions"
    )
    left = models.ForeignKey(
        MemoryItem, on_delete=models.CASCADE, related_name="contradictions_as_left"
    )
    right = models.ForeignKey(
        MemoryItem, on_delete=models.CASCADE, related_name="contradictions_as_right"
    )
    detected_at = models.DateTimeField()
    detector = models.CharField(max_length=80)  # rule/embedding/human
    severity = models.CharField(
        max_length=16, choices=E.RiskClass.choices(), default=E.RiskClass.LOW
    )
    status = models.CharField(max_length=24, default="OPEN")  # OPEN/RESOLVED/IGNORED
    resolution = models.TextField(blank=True)
    resolved_memory = models.ForeignKey(
        MemoryItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_contradictions",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "memory_contradiction"
        indexes = [
            models.Index(fields=["persona", "status", "detected_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["left", "right"], name="memory_contradiction_unique_pair"
            ),
            models.CheckConstraint(
                condition=~models.Q(left=models.F("right")),
                name="memory_contradiction_no_self",
            ),
        ]


class MemoryContextPack(UUIDModel):
    """Šta je zaista ušlo u jedan prompt. Canon §1, §16.3.

    Bez ovoga „memory precision ≥ 95%" ostaje nemerljiv na produkciji:
    znalo bi se šta je u bazi, ali ne i šta je model video. Sadržaj se ne
    duplira — čuvaju se ID-jevi, skorovi i hash, pa se pakovanje može
    rekonstruisati i uporediti sa ishodom.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="context_packs"
    )
    run = models.ForeignKey(
        "orchestration.AgentRun",
        on_delete=models.CASCADE,
        related_name="context_packs",
    )
    purpose = models.CharField(max_length=24, choices=E.LLMPurpose.choices())
    query_text = models.TextField(blank=True)
    memory_ids = JSON_LIST(help_text="UUID-jevi odabranih memorija, redom.")
    scores = JSON_DICT(help_text='{"<memory_id>": {"R": 0.81, "semantic": 0.74}}')
    token_count = models.PositiveIntegerField(default=0)
    truncated = models.BooleanField(default=False)
    pack_hash = models.CharField(max_length=64)
    built_at = models.DateTimeField()

    class Meta:
        db_table = "memory_context_pack"
        indexes = [
            models.Index(fields=["run", "built_at"]),
            models.Index(fields=["persona", "purpose", "built_at"]),
        ]


class KnowledgeSource(UUIDModel):
    """Dokument, URL ili interna baza koju persona sme da koristi."""

    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="knowledge_sources",
        help_text="NULL znači izvor deljen između persona.",
    )
    source_kind = models.CharField(max_length=32, choices=E.SourceKind.choices())
    title = models.CharField(max_length=220)
    uri = models.TextField(blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    trust_score = unit_interval()
    is_active = models.BooleanField(default=True)
    retrieved_at = models.DateTimeField(null=True, blank=True)
    ingested_at = models.DateTimeField(null=True, blank=True)
    robots_allowed = models.BooleanField(
        null=True,
        blank=True,
        help_text="Canon §12.6 — web.read_public traži robots_respected.",
    )

    class Meta:
        db_table = "memory_knowledge_source"
        indexes = [
            models.Index(fields=["persona", "is_active"]),
            models.Index(fields=["checksum"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(trust_score__gte=0) & models.Q(trust_score__lte=1),
                name="knowledge_source_trust_unit",
            )
        ]

    def __str__(self) -> str:
        return self.title


class KnowledgeFact(UUIDModel):
    """Normalizovana činjenica izvedena iz izvora: subject–predicate–object."""

    source = models.ForeignKey(
        KnowledgeSource, on_delete=models.CASCADE, related_name="facts"
    )
    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="knowledge_facts",
    )
    subject = models.CharField(max_length=220)
    predicate = models.CharField(max_length=120)
    object_json = JSON_DICT()
    provenance = models.CharField(max_length=24, choices=E.Provenance.choices())
    confidence = unit_interval()
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "memory_knowledge_fact"
        indexes = [
            models.Index(fields=["persona", "subject", "predicate"]),
            models.Index(fields=["source"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=1),
                name="knowledge_fact_confidence_unit",
            )
        ]
