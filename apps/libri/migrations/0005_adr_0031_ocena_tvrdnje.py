# ADR-0031 sloj 4b §3.3: pouzdanost tvrdnje po pet osa (OcenaTvrdnje).
import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def _unit():
    return models.DecimalField(
        decimal_places=3, max_digits=4,
        validators=[django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(1)])


class Migration(migrations.Migration):

    dependencies = [
        ("libri", "0004_adr_0031_entiteti_odnosi"),
        ("memory", "0011_adr_0120_knowledge_embedding"),
    ]

    operations = [
        migrations.CreateModel(
            name="OcenaTvrdnje",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("pouzdanost", _unit()),
                ("nezavisnost", _unit()),
                ("blizina", _unit()),
                ("potkrepljenost", _unit()),
                ("stabilnost", _unit()),
                ("ukupno", _unit()),
                ("object_json", models.JSONField(blank=True, default=dict)),
                ("fact", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="libri_ocene", to="memory.knowledgefact")),
            ],
            options={"db_table": "libri_ocena_tvrdnje"},
        ),
        migrations.AddConstraint(
            model_name="ocenatvrdnje",
            constraint=models.UniqueConstraint(
                fields=["fact"], name="libri_ocena_unique_fact"),
        ),
        migrations.AddConstraint(
            model_name="ocenatvrdnje",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("pouzdanost__gte", 0), ("pouzdanost__lte", 1),
                    ("nezavisnost__gte", 0), ("nezavisnost__lte", 1),
                    ("blizina__gte", 0), ("blizina__lte", 1),
                    ("potkrepljenost__gte", 0), ("potkrepljenost__lte", 1),
                    ("stabilnost__gte", 0), ("stabilnost__lte", 1),
                    ("ukupno__gte", 0), ("ukupno__lte", 1),
                ),
                name="libri_ocena_axes_unit"),
        ),
    ]
