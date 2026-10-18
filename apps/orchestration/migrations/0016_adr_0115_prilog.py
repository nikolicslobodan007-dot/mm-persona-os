"""ADR-0115 — prilog uz čovekovu poruku (veza ili fajl)."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0015_adr_0110_poruka_delovi"),
        ("visuals", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Prilog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("vrsta", models.CharField(
                    choices=[("veza", "veza"), ("fajl", "fajl")], max_length=8)),
                ("naziv", models.CharField(max_length=300)),
                ("url", models.CharField(blank=True, max_length=1000)),
                ("asset", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="prilozi", to="visuals.mediaasset")),
                ("poruka", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="prilozi", to="orchestration.poruka")),
            ],
            options={"db_table": "orchestration_prilog"},
        ),
        migrations.AddIndex(
            model_name="prilog",
            index=models.Index(fields=["poruka", "created_at"],
                               name="orch_prilog_poruka_idx"),
        ),
    ]
