# ADR-0031 sloj 2: LibriDocument.source (KnowledgeSource) + checksum (dedup uvoza).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("libri", "0001_initial"),
        ("memory", "0011_adr_0120_knowledge_embedding"),
    ]

    operations = [
        migrations.AddField(
            model_name="libridocument",
            name="source",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="libri_documents",
                to="memory.knowledgesource",
            ),
        ),
        migrations.AddField(
            model_name="libridocument",
            name="checksum",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
