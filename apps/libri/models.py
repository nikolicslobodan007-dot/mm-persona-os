"""Libri — sloj znanja nad dokumentima (ADR-0031).

Prvi sloj (temelj): dokument se melje u LKP blokove (shema `lkp-0.1`, presedan
Grinder). Blok je jedinica teksta po strani i sekciji — `apps/memory` pamti po
događaju, a `KnowledgeFact`/`KnowledgeSource` ostaju sloj „tvrdnja → izvor" koji
se gradi NAD blokovima (kasniji sloj). Ovde još nema uvoza, tvrdnji ni veze na
`KnowledgeSource` — to dolazi pri uvozu (sloj 2).

`block_type` je `CharField` + CHECK (`paragraph|heading`), a ne enum: enum-ovi
žive samo u `common/enums.py` (Canon §20, zaštićena zona), a lkp-0.1 za sada daje
samo ta dva tipa bloka.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from pgvector.django import VectorField

from common.models import JSON_DICT, JSON_LIST, UUIDModel, unit_interval

LKP_SCHEMA_VERSION = "lkp-0.1"
BLOCK_TYPES = ("paragraph", "heading")


class LibriDocument(UUIDModel):
    """Manifest samljevenog dokumenta (LKP paket)."""

    # LKP `document_id` — stabilan identitet paketa; javni ključ za `libri` komande.
    document_id = models.CharField(max_length=64, unique=True)
    version_id = models.CharField(max_length=64, blank=True)
    title = models.CharField(max_length=220)
    language = models.CharField(max_length=16, blank=True)
    script = models.CharField(max_length=16, blank=True)
    pages = models.PositiveIntegerField(default=0)
    schema_version = models.CharField(max_length=16, default=LKP_SCHEMA_VERSION)
    running_headers_removed = JSON_LIST()
    ingested_at = models.DateTimeField(null=True, blank=True)
    # ADR-0031 sloj 2: izvor sa licencom (KnowledgeSource) + checksum za dedup.
    # `source` je null jer je sloj 1 napravio dokument bez njega; uvoz ga popuni.
    source = models.ForeignKey(
        "memory.KnowledgeSource", on_delete=models.CASCADE,
        null=True, blank=True, related_name="libri_documents",
    )
    checksum = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "libri_document"

    def __str__(self) -> str:
        return self.title


class Block(UUIDModel):
    """LKP blok (`lkp-0.1`): jedinica teksta po strani i sekciji."""

    document = models.ForeignKey(
        LibriDocument, on_delete=models.CASCADE, related_name="blocks",
    )
    block_id = models.CharField(max_length=64)
    version_id = models.CharField(max_length=64, blank=True)
    # paragraph | heading — CHECK, ne enum (Canon §20).
    block_type = models.CharField(max_length=16)
    text = models.TextField()
    language = models.CharField(max_length=16, blank=True)
    order = models.PositiveIntegerField()
    heading_path = JSON_LIST()
    # lkp-0.1 `source{page, section}` razdvojeno radi upita po strani/sekciji.
    source_page = models.PositiveIntegerField(null=True, blank=True)
    source_section = models.CharField(max_length=220, blank=True)
    # lkp-0.1 `permissions{ai_read, quote, export}`.
    perm_ai_read = models.BooleanField(default=True)
    perm_quote = models.BooleanField(default=True)
    perm_export = models.BooleanField(default=True)
    # lkp-0.1 `quality{extraction_confidence, human_verified}`.
    extraction_confidence = unit_interval()
    human_verified = models.BooleanField(default=False)
    previous_block_id = models.CharField(max_length=64, blank=True)
    next_block_id = models.CharField(max_length=64, blank=True)
    parent_section_id = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "libri_block"
        indexes = [
            models.Index(fields=["document", "order"],
                         name="libri_block_doc_order_idx"),
            models.Index(fields=["document", "source_page"],
                         name="libri_block_doc_page_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "block_id"],
                name="libri_block_unique_in_document",
            ),
            models.CheckConstraint(
                condition=models.Q(extraction_confidence__gte=0)
                & models.Q(extraction_confidence__lte=1),
                name="libri_block_confidence_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(block_type__in=BLOCK_TYPES),
                name="libri_block_type_vocab",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document.document_id}#{self.order}"


class BlockEmbedding(UUIDModel):
    """Vektor Libri bloka za semantičku pretragu (ADR-0031, sloj 3).

    Odvojen zapis kao `KnowledgeEmbedding` — re-embedding bez diranja bloka, više
    modela uz isti blok (Canon §10.5). Koristi isti semantički model kao veštine
    (`VESTINA_EMBEDDING_MODEL`, MiniLM-L12). Vektor je indeks za pronalaženje
    kandidata, nikad izvor istine (Canon §4.1). Bez HNSW indeksa za sada: korpus
    je mali, sekvencijalna kosinusna pretraga je trenutna (ista nota kao
    `KnowledgeEmbedding`)."""

    block = models.ForeignKey(
        Block, on_delete=models.CASCADE, related_name="embeddings",
    )
    model_key = models.CharField(max_length=120)
    dimensions = models.PositiveSmallIntegerField(
        help_text="Zapisano uz vektor: Canon §10.5 traži novu kolonu, ne izmenu.",
    )
    embedding = VectorField(dimensions=settings.VESTINA_EMBEDDING_DIM)
    text_hash = models.CharField(
        max_length=64, blank=True,
        help_text="Memory v0.1 §6 — isti tekst i isti model → vektor se ne računa ponovo.",
    )

    class Meta:
        db_table = "libri_block_embedding"
        constraints = [
            models.UniqueConstraint(
                fields=["block", "model_key"],
                name="libri_block_embedding_unique_model",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.block.block_id}@{self.model_key}"


# ADR-0031 sloj 4b: registar entiteta + graf odnosa.
ENTITY_KINDS = ("osoba", "organizacija", "dogadjaj")
RELATION_TYPES = ("radi_u", "vodi", "deo_od", "nalazi_se_u", "osnovao")


class Entitet(UUIDModel):
    """Entitet iz dokumenta (ADR-0031 sloj 4b): osoba, organizacija ili događaj.

    Danas odnos postoji samo posredno kroz tvrdnju; ovde dobija karton. Vrsta je
    `CharField` + CHECK, ne enum (Canon §20). Dvostruko vreme (ADR-0031 §3.2):
    `desilo_se` (kada se događaj desio) i `objavljeno` (kada ga je izvor objavio)
    — dva polja, ne jedno. Poreklo do bloka je u `object_json` (Canon §4.1).
    """

    source = models.ForeignKey(
        "memory.KnowledgeSource", on_delete=models.CASCADE,
        related_name="libri_entities",
    )
    kind = models.CharField(max_length=16)  # osoba | organizacija | dogadjaj (CHECK)
    name = models.CharField(max_length=220)
    normalized = models.CharField(max_length=220)
    aliases = JSON_LIST()
    desilo_se = models.DateTimeField(null=True, blank=True)
    objavljeno = models.DateTimeField(null=True, blank=True)
    confidence = unit_interval()
    object_json = JSON_DICT()

    class Meta:
        db_table = "libri_entitet"
        indexes = [
            models.Index(fields=["source", "kind"],
                         name="libri_entitet_src_kind_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "kind", "normalized"],
                name="libri_entitet_unique_in_source",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=ENTITY_KINDS),
                name="libri_entitet_kind_vocab",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=1),
                name="libri_entitet_confidence_unit",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"


class Odnos(UUIDModel):
    """Usmerena veza između dva entiteta (ADR-0031 sloj 4b graf).

    Tip veze je `CharField` + CHECK (ne enum, Canon §20); `confidence` je
    pouzdanost VEZE. Poreklo do bloka u `object_json`. Odnos ne sme da postoji
    bez oba entiteta i bez izvora (Canon §4.1).
    """

    source = models.ForeignKey(
        "memory.KnowledgeSource", on_delete=models.CASCADE,
        related_name="libri_relations",
    )
    subject = models.ForeignKey(
        Entitet, on_delete=models.CASCADE, related_name="odnosi_od",
    )
    object = models.ForeignKey(
        Entitet, on_delete=models.CASCADE, related_name="odnosi_do",
    )
    relation_type = models.CharField(max_length=24)  # radi_u | vodi | ... (CHECK)
    confidence = unit_interval()
    object_json = JSON_DICT()

    class Meta:
        db_table = "libri_odnos"
        indexes = [
            models.Index(fields=["source"], name="libri_odnos_source_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(relation_type__in=RELATION_TYPES),
                name="libri_odnos_type_vocab",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=1),
                name="libri_odnos_confidence_unit",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subject_id}-{self.relation_type}->{self.object_id}"
