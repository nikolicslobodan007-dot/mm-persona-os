# ADR-0031 sloj 4b: registar entiteta + graf odnosa (dvostruko vreme na događaju).
import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("libri", "0003_adr_0031_block_embedding"),
        ("memory", "0011_adr_0120_knowledge_embedding"),
    ]

    operations = [
        migrations.CreateModel(
            name="Entitet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(max_length=16)),
                ("name", models.CharField(max_length=220)),
                ("normalized", models.CharField(max_length=220)),
                ("aliases", models.JSONField(blank=True, default=list)),
                ("desilo_se", models.DateTimeField(blank=True, null=True)),
                ("objavljeno", models.DateTimeField(blank=True, null=True)),
                ("confidence", models.DecimalField(
                    decimal_places=3, max_digits=4,
                    validators=[django.core.validators.MinValueValidator(0),
                                django.core.validators.MaxValueValidator(1)])),
                ("object_json", models.JSONField(blank=True, default=dict)),
                ("source", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="libri_entities", to="memory.knowledgesource")),
            ],
            options={"db_table": "libri_entitet"},
        ),
        migrations.CreateModel(
            name="Odnos",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("relation_type", models.CharField(max_length=24)),
                ("confidence", models.DecimalField(
                    decimal_places=3, max_digits=4,
                    validators=[django.core.validators.MinValueValidator(0),
                                django.core.validators.MaxValueValidator(1)])),
                ("object_json", models.JSONField(blank=True, default=dict)),
                ("source", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="libri_relations", to="memory.knowledgesource")),
                ("subject", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="odnosi_od", to="libri.entitet")),
                ("object", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="odnosi_do", to="libri.entitet")),
            ],
            options={"db_table": "libri_odnos"},
        ),
        migrations.AddIndex(
            model_name="entitet",
            index=models.Index(fields=["source", "kind"],
                               name="libri_entitet_src_kind_idx"),
        ),
        migrations.AddConstraint(
            model_name="entitet",
            constraint=models.UniqueConstraint(
                fields=["source", "kind", "normalized"],
                name="libri_entitet_unique_in_source"),
        ),
        migrations.AddConstraint(
            model_name="entitet",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind__in", ("osoba", "organizacija", "dogadjaj"))),
                name="libri_entitet_kind_vocab"),
        ),
        migrations.AddConstraint(
            model_name="entitet",
            constraint=models.CheckConstraint(
                condition=models.Q(("confidence__gte", 0), ("confidence__lte", 1)),
                name="libri_entitet_confidence_unit"),
        ),
        migrations.AddIndex(
            model_name="odnos",
            index=models.Index(fields=["source"], name="libri_odnos_source_idx"),
        ),
        migrations.AddConstraint(
            model_name="odnos",
            constraint=models.CheckConstraint(
                condition=models.Q(("relation_type__in",
                                    ("radi_u", "vodi", "deo_od", "nalazi_se_u", "osnovao"))),
                name="libri_odnos_type_vocab"),
        ),
        migrations.AddConstraint(
            model_name="odnos",
            constraint=models.CheckConstraint(
                condition=models.Q(("confidence__gte", 0), ("confidence__lte", 1)),
                name="libri_odnos_confidence_unit"),
        ),
    ]
