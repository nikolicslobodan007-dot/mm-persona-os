"""ADR-0073 — spisak fajlova koje pisac sme da čita, po zadatku."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("orchestration", "0011_zakup_zadatka")]

    operations = [
        migrations.AddField(
            model_name="codetask",
            name="reference_paths",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
