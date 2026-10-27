# ADR-0031 (opcija B): nova svrha rute `extract` (common/enums.py, zaštićena zona).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("memory", "0011_adr_0120_knowledge_embedding"),
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
                    ("extract", "extract"),
                ],
                max_length=24,
            ),
        ),
    ]
