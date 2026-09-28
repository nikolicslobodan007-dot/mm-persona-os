"""Kućni stil iz Pravopisa — upis i pregled. ADR-0054.

    manage.py kucni_stil --spisak
    manage.py kucni_stil --upisi
    manage.py kucni_stil --ugasi futur-sazeti --zasto "..."

Ova pravila idu u **svaki** prompt za pisanje, svakom agentu. Zato se upisuju
ručno i gase ručno — ne nastaju iz odluke urednika kao ostale pouke (ADR-0014),
nego iz knjige.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.content import lessons
from apps.content.models import EditorialLesson
from apps.content.pravopis import KLJUCEVI, PRAVILA


class Command(BaseCommand):
    help = "Upisuje pravopisni kućni stil koji važi za sve agente (ADR-0054)."

    def add_arguments(self, parser):
        parser.add_argument("--spisak", action="store_true")
        parser.add_argument("--upisi", action="store_true")
        parser.add_argument("--ugasi", default="", help="Ključ pravila.")
        parser.add_argument("--zasto", default="")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, spisak, upisi, ugasi, zasto, actor, **opts):
        if not actor.startswith("user:"):
            raise CommandError("Kućni stil postavlja čovek; `--actor` počinje sa `user:`.")
        if sum(map(bool, (spisak, upisi, ugasi))) != 1:
            raise CommandError("Treba tačno jedno: --spisak, --upisi ili --ugasi.")
        with bind(actor_id=actor):
            if spisak:
                return self._spisak()
            if upisi:
                return self._upisi(actor)
            return self._ugasi(ugasi, zasto, actor)

    def _spisak(self) -> None:
        for p in PRAVILA:
            oznaka = f"[pravopis:{p.kljuc}]"
            red = EditorialLesson.objects.filter(
                persona__isnull=True, department__isnull=True,
                text__startswith=oznaka).first()
            stanje = ("nije upisano" if red is None
                      else ("aktivno" if red.is_active else "ugašeno"))
            boja = self.style.SUCCESS if stanje == "aktivno" else (
                self.style.ERROR if stanje == "nije upisano" else (lambda s: s))
            self.stdout.write(f"{p.kljuc:20} t. {p.tacka:5} {boja(stanje)}")
            self.stdout.write(f"    {p.tekst[:150]}")
            if p.pre:
                self.stdout.write(f"    ne:  {p.pre}")
                self.stdout.write(f"    da:  {p.posle}")

    def _upisi(self, actor: str) -> None:
        br = lessons.upisi_kucni_stil(actor=actor)
        self.stdout.write(self.style.SUCCESS(
            f"upisano {br['upisano']}, izmenjeno {br['izmenjeno']}, "
            f"netaknuto {br['netaknuto']}"))
        self.stdout.write("Od sada idu u svaki prompt za pisanje, svakom agentu.")

    def _ugasi(self, kljuc: str, zasto: str, actor: str) -> None:
        if kljuc not in KLJUCEVI:
            raise CommandError(f"Nepoznat ključ {kljuc!r}; poznati: {sorted(KLJUCEVI)}")
        if not zasto.strip():
            raise CommandError("Uz `--ugasi` ide `--zasto` sa razlogom.")
        red = EditorialLesson.objects.filter(
            persona__isnull=True, department__isnull=True,
            text__startswith=f"[pravopis:{kljuc}]").first()
        if red is None:
            raise CommandError(f"Pravilo {kljuc!r} nije upisano.")
        red.is_active = False
        red.save(update_fields=["is_active", "updated_at"])
        from api import audit
        audit.record("content.house_style.disabled",
                     details={"kljuc": kljuc, "razlog": zasto.strip()[:500],
                              "actor": actor})
        self.stdout.write(self.style.WARNING(f"{kljuc} ugašeno: {zasto.strip()[:120]}"))
