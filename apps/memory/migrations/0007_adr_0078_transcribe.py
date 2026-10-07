# ADR-0078: nova svrha rute `transcribe` (common/enums.py, zaštićena zona).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("memory", "0006_adr_0059_licenca_izvora"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memorycontextpack",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("planning", "planning"),
                    ("content_draft", "content_draft"),
                    ("reply", "reply"),
                    ("summarise", "summarise"),
                    ("classify", "classify"),
                    ("embed", "embed"),
                    ("evaluate", "evaluate"),
                    ("code_patch", "code_patch"),
                    ("transcribe", "transcribe"),
                ],
                max_length=24,
            ),
        ),
    ]
