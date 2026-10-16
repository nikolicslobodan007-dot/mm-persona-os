"""ADR-0096 — `MemoryContextPack` pamti koje su veštine ušle u paket.

Isti obrazac kao `memory_ids`: bez ovog polja ne možemo da odgovorimo na
pitanje „na šta se agent oslonio kad je ovo napisao" za veštine iz baze
znanja, a to pitanje se postavlja svaki put kad nešto krene naopako.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("memory", "0008_adr_0077_commit_i_putanja")]

    operations = [
        migrations.AddField(
            model_name="memorycontextpack",
            name="vestina_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="ADR-0096 — UUID-jevi veština (KnowledgeFact) koje su ušle "
                          "u paket, redom.",
            ),
        ),
    ]
