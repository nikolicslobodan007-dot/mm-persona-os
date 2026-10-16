"""ADR-0105 — nit razgovora između čoveka i direktora.

Do sada je svaki posao počinjao komandom u terminalu: firma nije imala
ulazna vrata. Ove dve tabele su ta vrata.

`created_at` i `updated_at` dolaze iz `UUIDModel` (common/models.py) i zato
stoje i ovde — prvi pokušaj ih je izostavio, pa kolone nisu nastale i svaki
upis je pucao. Imena indeksa su naša i upisana u modelu, da ih Django ne bi
preimenovao pri sledećoj proveri migracija.
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
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("naslov", models.CharField(blank=True, max_length=200)),
                ("human_owner", models.CharField(
                    help_text="Čovek koji vodi nit (`user:…`).", max_length=120)),
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
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("autor", models.CharField(
                    choices=[("covek", "čovek"), ("agent", "agent")], max_length=8)),
                ("autor_ref", models.CharField(
                    help_text="`user:slobodan` ili `P-00003`.", max_length=120)),
                ("telo", models.TextField()),
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
            index=models.Index(fields=["human_owner", "-updated_at"],
                               name="orch_razgovor_owner_idx"),
        ),
        migrations.AddIndex(
            model_name="poruka",
            index=models.Index(fields=["razgovor", "created_at"],
                               name="orch_poruka_nit_idx"),
        ),
    ]
