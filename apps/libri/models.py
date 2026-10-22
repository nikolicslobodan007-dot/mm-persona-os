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

from django.db import models

from common.models import JSON_LIST, UUIDModel, unit_interval

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
