"""ADR-0101 — izvor znanja zna kom sektoru korporacije pripada.

Bez ovog polja izbor veština za paket pada na azbuku (ADR-0096 tačka 5):
izmereno 16.10.2026, sa 452 veštine u bazi u paket je ulazilo devet, uvek
istih devet. Vokabular su `Department.code` iz ADR-0017, ne nova podela.
Prazno znači „važi za sve sektore".
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("memory", "0009_adr_0096_vestina_ids")]

    operations = [
        migrations.AddField(
            model_name="knowledgesource",
            name="sector",
            field=models.CharField(
                blank=True,
                help_text="ADR-0101 — Department.code sektora kome korpus pripada. "
                          "Prazno znači da važi za sve sektore.",
                max_length=32),
        ),
    ]
