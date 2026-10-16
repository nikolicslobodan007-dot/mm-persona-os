"""ADR-0077 §3 — korpus iz repozitorijuma nosi commit i putanju fajla.

Isti `uri` u repozitorijumu daje različit sadržaj u različitim trenucima —
sama adresa ne kaže ŠTA je tačno pročitano. Ovde se dodaju dva polja koja to
beleže; oba su prazna za izvore koji nisu iz repozitorijuma.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("memory", "0007_adr_0078_transcribe")]

    operations = [
        migrations.AddField(
            model_name="knowledgesource",
            name="commit_sha",
            field=models.CharField(
                blank=True,
                help_text="ADR-0077 §3 — commit iz kog je pročitan sadržaj. Prazno za "
                          "izvore koji nisu iz repozitorijuma.",
                max_length=40),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="file_path",
            field=models.TextField(
                blank=True,
                help_text="ADR-0077 §3 — putanja fajla u repozitorijumu. Prazno za "
                          "izvore koji nisu iz repozitorijuma."),
        ),
    ]
