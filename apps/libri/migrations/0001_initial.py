# ADR-0031 — Libri: sloj znanja (LKP blokovi) kao trinaesti app (Canon §1 +libri).

import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="LibriDocument",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("document_id", models.CharField(max_length=64, unique=True)),
                ("version_id", models.CharField(blank=True, max_length=64)),
                ("title", models.CharField(max_length=220)),
                ("language", models.CharField(blank=True, max_length=16)),
                ("script", models.CharField(blank=True, max_length=16)),
                ("pages", models.PositiveIntegerField(default=0)),
                ("schema_version", models.CharField(default="lkp-0.1", max_length=16)),
                ("running_headers_removed", models.JSONField(blank=True, default=list)),
                ("ingested_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "libri_document",
            },
        ),
        migrations.CreateModel(
            name="Block",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("block_id", models.CharField(max_length=64)),
                ("version_id", models.CharField(blank=True, max_length=64)),
                ("block_type", models.CharField(max_length=16)),
                ("text", models.TextField()),
                ("language", models.CharField(blank=True, max_length=16)),
                ("order", models.PositiveIntegerField()),
                ("heading_path", models.JSONField(blank=True, default=list)),
                ("source_page", models.PositiveIntegerField(blank=True, null=True)),
                ("source_section", models.CharField(blank=True, max_length=220)),
                ("perm_ai_read", models.BooleanField(default=True)),
                ("perm_quote", models.BooleanField(default=True)),
                ("perm_export", models.BooleanField(default=True)),
                (
                    "extraction_confidence",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=4,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(1),
                        ],
                    ),
                ),
                ("human_verified", models.BooleanField(default=False)),
                ("previous_block_id", models.CharField(blank=True, max_length=64)),
                ("next_block_id", models.CharField(blank=True, max_length=64)),
                ("parent_section_id", models.CharField(blank=True, max_length=64)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocks",
                        to="libri.libridocument",
                    ),
                ),
            ],
            options={
                "db_table": "libri_block",
            },
        ),
        migrations.AddIndex(
            model_name="block",
            index=models.Index(
                fields=["document", "order"], name="libri_block_doc_order_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="block",
            index=models.Index(
                fields=["document", "source_page"], name="libri_block_doc_page_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="block",
            constraint=models.UniqueConstraint(
                fields=["document", "block_id"], name="libri_block_unique_in_document"
            ),
        ),
        migrations.AddConstraint(
            model_name="block",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("extraction_confidence__gte", 0),
                    ("extraction_confidence__lte", 1),
                ),
                name="libri_block_confidence_unit",
            ),
        ),
        migrations.AddConstraint(
            model_name="block",
            constraint=models.CheckConstraint(
                condition=models.Q(("block_type__in", ("paragraph", "heading"))),
                name="libri_block_type_vocab",
            ),
        ),
    ]
