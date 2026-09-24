"""Zapošljavanje agenta iz komandne linije. ADR-0023.

    manage.py zaposli --ime "Jovan Ilić" --mesto URE-SR
    manage.py zaposli --ime "Ana Perić" --mesto POD-SR --nise ai,podrska \\
                      --rodjen Niš --zivi Beograd --visina 168 --tezina 60

Radna mesta se vide komandom `manage.py seed_org --spisak` ili na strani
Organizacija u konzoli.
"""

from __future__ import annotations

import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.personas import hiring, org
from apps.personas.models import Position


class Command(BaseCommand):
    help = "Pravi novog agenta, postavlja ga na radno mesto i vodi do READY."

    def add_arguments(self, parser):
        parser.add_argument("--ime", required=True, help="Ime i prezime, bez „(AI)”.")
        parser.add_argument("--mesto", required=True, help="Šifra radnog mesta.")
        parser.add_argument("--nise", default="", help="Liste tema, zarezom.")
        parser.add_argument("--actor", default="user:slobodan")
        # Dosije je neobavezan — agent sme da radi i pre nego što dobije lice.
        parser.add_argument("--rodjen", default="")
        parser.add_argument("--zivi", default="")
        parser.add_argument("--datum-rodjenja", default="", dest="dob",
                            help="GGGG-MM-DD; agent je najmanje 22 godine star.")
        parser.add_argument("--visina", type=int, default=0)
        parser.add_argument("--tezina", type=int, default=0)

    def handle(self, *args, ime, mesto, nise, actor, rodjen, zivi, dob, visina,
               tezina, **opts):
        position = Position.objects.filter(code=mesto).select_related(
            "department").first()
        if position is None:
            imena = ", ".join(Position.objects.order_by("code").values_list(
                "code", flat=True)[:20])
            raise CommandError(f"Radno mesto „{mesto}” ne postoji. Ima: {imena}")
        try:
            with bind(actor_id=actor):
                persona = hiring.hire(
                    name=ime, position=position, actor=actor,
                    niches=[n for n in (nise or "").split(",") if n.strip()])
                polja = {}
                if rodjen:
                    polja["birth_place"] = rodjen
                if zivi:
                    polja["residence"] = zivi
                if visina:
                    polja["height_cm"] = visina
                if tezina:
                    polja["weight_kg"] = tezina
                rodjendan = date.fromisoformat(dob) if dob else None
                if polja or rodjendan:
                    org.set_dossier(persona, actor=actor, birth_date=rodjendan,
                                    **polja)
        except (hiring.HiringError, org.OrgError, ValueError) as e:
            raise CommandError(str(e)) from e

        boss = org.manager_of(persona)
        self.stdout.write(self.style.SUCCESS(
            f"{persona.public_id} — {persona.display_name}, "
            f"{position.department.name} / {position.title}, {persona.status}."))
        self.stdout.write(f"  odgovara: {boss.display_name if boss else 'čoveku'}")
        self.stdout.write(f"  poverenje: {persona.trust_level} na svemu — "
                          "radno mesto ne daje nijednu dozvolu.")
        if not nise:
            self.stdout.write(self.style.WARNING(
                "  bez niša: World Engine mu neće naći nijedan relevantan događaj."))
        self._kljuc(persona)
        self.stdout.write("  sledeće: portret, pa poverenje po potrebi.")

    def _kljuc(self, persona) -> None:
        """Agent bez svog ključa tiho piše lokalnim šablonom (ADR-0013/0024)."""
        from apps.llm_gateway import gateway

        ime = gateway.persona_env_name("anthropic", persona)
        if ime and os.environ.get(ime, "").strip():
            self.stdout.write(f"  ključ modela: {ime} ✓")
            return
        self.stdout.write(self.style.WARNING(
            f"  nema ključ modela — dodaj `{ime}=…` u .env.prod, "
            "inače mu nacrte piše lokalni šablon."))
