# ADR-0031 sloj 3: semantička pretraga — vektor Libri bloka u zasebnoj tabeli.
import uuid

import django.db.models.deletion
import pgvector.django.vector
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("libri", "0002_adr_0031_source_checksum"),
    ]

    operations = [
        migrations.CreateModel(
            name="BlockEmbedding",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("model_key", models.CharField(max_length=120)),
                ("dimensions", models.PositiveSmallIntegerField(
                    help_text="Zapisano uz vektor: Canon §10.5 traži novu kolonu, ne izmenu.")),
                ("embedding", pgvector.django.vector.VectorField(dimensions=384)),
                ("text_hash", models.CharField(
                    blank=True, max_length=64,
                    help_text="Memory v0.1 §6 — isti tekst i isti model → vektor se ne računa ponovo.")),
                ("block", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="embeddings", to="libri.block")),
            ],
            options={"db_table": "libri_block_embedding"},
        ),
        migrations.AddConstraint(
            model_name="blockembedding",
            constraint=models.UniqueConstraint(
                fields=("block", "model_key"), name="libri_block_embedding_unique_model"),
        ),
    ]
