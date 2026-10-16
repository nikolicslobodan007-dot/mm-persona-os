"""ADR-0105, ispravka — `updated_at` iz `UUIDModel`, bez `last_at`.

Prva migracija (0013) je napisana rukom i izostavila je `created_at` i
`updated_at`, koje donosi `UUIDModel`. Pošto je 0013 **već bila primenjena u
produkciji**, njen sadržaj se ne menja: Django primenjenu migraciju ne
pokreće ponovo, pa bi ispravka u njoj popravila samo nove baze, a produkciju
ostavila bez kolone. Izmereno: `UndefinedColumn: column
orchestration_razgovor.updated_at does not exist`, 16.10.2026.

Zato ova migracija dopunjava ono što 0013 nije donela:

  - `updated_at` na obe tabele,
  - `created_at` dobija `db_index`, koji bazna klasa traži a 0013 nije dala,
  - `last_at` se uklanja — bio je duplikat `updated_at` iz bazne klase,
  - indeks niti ide na `-updated_at` i dobija ime koje stoji u modelu.
"""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("orchestration", "0013_adr_0105_razgovor")]

    operations = [
        migrations.AddField(
            model_name="poruka",
            name="updated_at",
            field=models.DateTimeField(auto_now=True,
                                       default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="razgovor",
            name="updated_at",
            field=models.DateTimeField(auto_now=True,
                                       default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="poruka",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AlterField(
            model_name="razgovor",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        # Indeks se sklanja pre polja na koje se oslanja.
        migrations.RemoveIndex(model_name="razgovor",
                               name="orch_razg_owner_last_idx"),
        migrations.RemoveField(model_name="razgovor", name="last_at"),
        migrations.AddIndex(
            model_name="razgovor",
            index=models.Index(fields=["human_owner", "-updated_at"],
                               name="orch_razgovor_owner_idx"),
        ),
    ]
