"""Rečnik uz Pravopis: uvoz, traženje reči, provera teksta. ADR-0055.

    manage.py recnik --uvezi
    manage.py recnik --nadji avlija
    manage.py recnik --proveri "Stigao je u havliju."
    manage.py recnik --stanje
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.content import recnik
from apps.memory.models import KnowledgeFact, KnowledgeSource


class Command(BaseCommand):
    help = "Uvozi i pretražuje Rečnik uz Pravopis (ADR-0055)."

    def add_arguments(self, parser):
        parser.add_argument("--uvezi", action="store_true")
        parser.add_argument("--nadji", default="", help="Reč koja se traži.")
        parser.add_argument("--proveri", default="", help="Tekst koji se proverava.")
        parser.add_argument("--stanje", action="store_true")
        parser.add_argument("--utisaj", default="", help="Oblik koji se isključuje.")
        parser.add_argument("--zasto", default="")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, uvezi, nadji, proveri, stanje, utisaj, zasto, actor, **opts):
        if sum(map(bool, (uvezi, nadji, proveri, stanje, utisaj))) != 1:
            raise CommandError(
                "Treba tačno jedno: --uvezi, --nadji, --proveri, --stanje, --utisaj.")
        if uvezi:
            if not actor.startswith("user:"):
                raise CommandError("Rečnik uvozi čovek; `--actor` počinje sa `user:`.")
            return self._uvezi(actor)
        if utisaj:
            if not actor.startswith("user:"):
                raise CommandError("Oblik utišava čovek; `--actor` počinje sa `user:`.")
            return self._utisaj(utisaj, zasto, actor)
        if stanje:
            return self._stanje()
        if nadji:
            return self._nadji(nadji)
        return self._proveri(proveri)

    def _uvezi(self, actor: str) -> None:
        if not recnik.DATOTEKA.exists():
            raise CommandError(f"Nema datoteke {recnik.DATOTEKA}.")
        with bind(actor_id=actor):
            br = recnik.uvezi(actor=actor)
        self.stdout.write(self.style.SUCCESS(
            f"upisano {br['upisano']} odrednica "
            f"(obrisano ranijih {br['obrisano']}), sa brojem tačke {br['sa tačkom']}, "
            f"zabranjenih oblika {br['odbijenih oblika']}"))

    def _stanje(self) -> None:
        izvor = KnowledgeSource.objects.filter(persona__isnull=True,
                                               title=recnik.IZVOR).first()
        if izvor is None:
            self.stdout.write(self.style.ERROR("Rečnik nije uvezen."))
            return
        qs = KnowledgeFact.objects.filter(source=izvor, predicate=recnik.PREDIKAT)
        ukupno = qs.count()
        self.stdout.write(f"{recnik.IZVOR}")
        self.stdout.write(f"  odrednica: {ukupno}")
        self.stdout.write(f"  sa brojem tačke: {qs.exclude(object_json__tacke=[]).count()}")
        self.stdout.write(f"  sa zabranjenim oblikom: {qs.exclude(object_json__ne=[]).count()}")

    def _nadji(self, rec: str) -> None:
        pogotci = recnik.nadji(rec)
        if not pogotci:
            self.stdout.write(self.style.WARNING(f"{rec}: nema odrednice."))
            return
        for p in pogotci:
            tacke = ", ".join(p["tacke"]) or "—"
            self.stdout.write(f"{self.style.SUCCESS(p['odrednica'])}  (t. {tacke}, "
                              f"str. {p['strana']})")
            self.stdout.write(f"    {p['tekst']}")

    def _proveri(self, tekst: str) -> None:
        nalazi = recnik.proveri(tekst)
        if not nalazi:
            self.stdout.write(self.style.SUCCESS("Nema oblika koje Pravopis odbija."))
            return
        for n in nalazi:
            self.stdout.write(self.style.ERROR(str(n)))
        self.stdout.write(f"\nukupno {len(nalazi)}; odluku donosi urednik "
                          f"— spisak je izveden iz teksta odrednica i ume da pogreši.")

    def _utisaj(self, oblik: str, zasto: str, actor: str) -> None:
        if not zasto.strip():
            raise CommandError("Uz `--utisaj` ide `--zasto` sa razlogom.")
        with bind(actor_id=actor):
            dirnuto = recnik.utisaj(oblik, actor=actor, razlog=zasto)
        if not dirnuto:
            raise CommandError(f"Oblik {oblik!r} nije ni bio u proveri.")
        self.stdout.write(self.style.WARNING(
            f"{oblik}: isključen iz provere u {dirnuto} odrednici/a — {zasto.strip()[:100]}"))
