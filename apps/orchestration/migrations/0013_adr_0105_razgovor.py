"""ADR-0105 — nit razgovora između čoveka i direktora.

Do sada je svaki posao počinjao komandom u terminalu: firma nije imala
ulazna vrata. Ove dve tabele su ta vrata.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0012_referenca_po_zadatku"),
        ("personas", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Razgovor",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("naslov", models.CharField(blank=True, max_length=200)),
                ("human_owner", models.CharField(
                    help_text="Čovek koji vodi nit (`user:…`).", max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_at", models.DateTimeField(auto_now=True)),
                ("persona", models.ForeignKey(
                    help_text="Sagovornik — agent sa kojim čovek priča (obično direktor).",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="razgovori", to="personas.persona")),
            ],
            options={"db_table": "orchestration_razgovor"},
        ),
        migrations.CreateModel(
            name="Poruka",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("autor", models.CharField(
                    choices=[("covek", "čovek"), ("agent", "agent")], max_length=8)),
                ("autor_ref", models.CharField(
                    help_text="`user:slobodan` ili `P-00003`.", max_length=120)),
                ("telo", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("plan", models.ForeignKey(
                    blank=True,
                    help_text="Posao koji je ova poruka pokrenula ili javila.",
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="poruke", to="orchestration.agentplan")),
                ("razgovor", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="poruke", to="orchestration.razgovor")),
            ],
            options={"db_table": "orchestration_poruka"},
        ),
        migrations.AddIndex(
            model_name="razgovor",
            index=models.Index(fields=["human_owner", "-last_at"],
                               name="orch_razg_owner_last_idx"),
        ),
        migrations.AddIndex(
            model_name="poruka",
            index=models.Index(fields=["razgovor", "created_at"],
                               name="orch_poruka_nit_idx"),
        ),
    ]
