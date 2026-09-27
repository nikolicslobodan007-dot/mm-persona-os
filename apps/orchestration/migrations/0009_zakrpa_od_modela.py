"""ADR-0050 — `TaskPatch.from_model`: da li je zakrpu napisao model.

Plafon pokušaja se do sad brojao po redovima u tabeli. Time je ponovna predaja
teksta koji je model već napisao (ADR-0048, naša ispravka naše greške) potrošila
agentu treći od tri pokušaja. Polje postoji da bi se brojalo ono što se stvarno
desilo — poziv modelu — a ne koliko redova ima zadatak.

Zatečeni redovi se popunjavaju po ceni: `cost_eur_cents > 0` znači da je poziv
plaćen, dakle da ga je pisao model. To nije doterivanje zapisa (ADR-0046): ne
menja se nijedna tvrdnja, nego se upisuje činjenica koja je u tim redovima već
stajala, u polje koje do sad nije postojalo. Ručne predaje i ponovne predaje
ostaju na `False` — što i jesu.
"""

from django.db import migrations, models


def po_ceni(apps, schema_editor):
    TaskPatch = apps.get_model("orchestration", "TaskPatch")
    TaskPatch.objects.filter(cost_eur_cents__gt=0).update(from_model=True)


def nazad(apps, schema_editor):
    """Polje se briše sa kolonom; povratak ne traži ništa."""


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0008_adr_0044_cena_zakrpe"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskpatch",
            name="from_model",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(po_ceni, nazad),
    ]
