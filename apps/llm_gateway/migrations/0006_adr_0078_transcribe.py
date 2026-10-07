# ADR-0078: nova svrha rute `transcribe` (common/enums.py, zaštićena zona).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("llm_gateway", "0005_adr_0044_code_patch"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agentroute",
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
        migrations.AlterField(
            model_name="llmroute",
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
        migrations.AlterField(
            model_name="promptrecord",
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
