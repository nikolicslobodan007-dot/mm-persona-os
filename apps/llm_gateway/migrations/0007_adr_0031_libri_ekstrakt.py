# ADR-0031 (opcija B): nova svrha rute `extract` (common/enums.py, zaštićena zona).

from django.db import migrations, models

_CHOICES = [
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
]


class Migration(migrations.Migration):

    dependencies = [
        ("llm_gateway", "0006_adr_0078_transcribe"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agentroute",
            name="purpose",
            field=models.CharField(choices=_CHOICES, max_length=24),
        ),
        migrations.AlterField(
            model_name="llmroute",
            name="purpose",
            field=models.CharField(choices=_CHOICES, max_length=24),
        ),
        migrations.AlterField(
            model_name="promptrecord",
            name="purpose",
            field=models.CharField(choices=_CHOICES, max_length=24),
        ),
    ]
