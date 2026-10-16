"""ADR-0110 — poruka nosi i razložen oblik, da konzola ne čita rečenice."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("orchestration", "0014_adr_0105_vremena_iz_bazne_klase")]

    operations = [
        migrations.AddField(
            model_name="poruka",
            name="delovi",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
