"""ADR-0059 §2 — izvor znanja nosi licencu, i to u bazi, ne u servisu."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("memory", "0005_adr_0044_code_patch")]

    operations = [
        migrations.AddField(
            model_name="knowledgesource",
            name="license_box",
            field=models.CharField(
                choices=[("SLOBODNA", "SLOBODNA"), ("ZARAZNA", "ZARAZNA"),
                         ("ZABRANJENA", "ZABRANJENA"), ("NEPOZNATA", "NEPOZNATA")],
                default="NEPOZNATA",
                help_text="ADR-0059 §2 — u koju kutiju pada licenca izvora.",
                max_length=16),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="license_note",
            field=models.CharField(
                blank=True,
                help_text="Tačan naziv licence kako stoji na izvoru (npr. `MIT`, `AGPL-3.0`).",
                max_length=200),
        ),
        migrations.AddIndex(
            model_name="knowledgesource",
            index=models.Index(fields=["license_box", "is_active"],
                               name="memory_know_license_a1f3c2_idx"),
        ),
        migrations.AddConstraint(
            model_name="knowledgesource",
            constraint=models.CheckConstraint(
                condition=~models.Q(source_kind="public_web_source") | ~models.Q(uri=""),
                name="knowledge_source_web_has_uri"),
        ),
        migrations.AddConstraint(
            model_name="knowledgesource",
            constraint=models.CheckConstraint(
                condition=~models.Q(license_box="SLOBODNA") | ~models.Q(license_note=""),
                name="knowledge_source_free_names_license"),
        ),
    ]
