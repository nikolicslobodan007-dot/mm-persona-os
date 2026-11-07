# ADR-0129 — rod sintetičke persone kao strukturno polje.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("visuals", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="visualprofile",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[
                    ("FEMALE", "FEMALE"),
                    ("MALE", "MALE"),
                    ("UNSPECIFIED", "UNSPECIFIED"),
                ],
                default="UNSPECIFIED",
                help_text="Rodni izgled sintetičke persone; bira 3D avatara (ADR-0129).",
                max_length=16,
            ),
        ),
    ]
