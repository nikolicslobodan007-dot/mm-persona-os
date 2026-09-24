"""Dosije agenta iz komandne linije. ADR-0017, dopuna ADR-0023.

    manage.py dosije --persona P-00002 --pokazi
    manage.py dosije --persona P-00002 --visina 183 --tezina 79 --gradja atletska \\
        --oci tamnosmeđe --kosa tamnosmeđa --frizura "kratka, uredna" \\
        --status "u vezi" --hobiji "planinarenje, stari bicikli, kuvanje" \\
        --izgled "Muškarac u ranim tridesetim, atletske građe…"

`--pokazi` ispisuje i **tekst za sliku**: tačno ono što se šalje generatoru,
odnosno ono što se nalepi u ChatGPT prozor dok slike pravimo ručno.

Opis izgleda je tekst koji je uneo čovek, pa prolazi iste tvrde zabrane kao i
poziv generatoru (ADR-0018) — greška se vidi ovde, a ne tek pred sliku.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.personas import org
from apps.personas.models import Persona

#: (zastavica, polje u dosijeu) — jedno mesto, da se spisak ne razilazi.
POLJA: tuple[tuple[str, str], ...] = (
    ("rodjen", "birth_place"), ("zivi", "residence"), ("gradja", "build"),
    ("oci", "eye_color"), ("kosa", "hair_color"), ("frizura", "hair_style"),
    ("obelezja", "distinguishing_marks"), ("status", "marital_status"),
    ("izgled", "appearance_prompt"),
)


class Command(BaseCommand):
    help = "Prikazuje i upisuje dosije agenta."

    def add_arguments(self, parser):
        parser.add_argument("--persona", required=True)
        parser.add_argument("--pokazi", action="store_true")
        parser.add_argument("--actor", default="user:slobodan")
        for zastavica, _polje in POLJA:
            parser.add_argument(f"--{zastavica}", default="")
        parser.add_argument("--visina", type=int, default=0)
        parser.add_argument("--tezina", type=int, default=0)
        parser.add_argument("--deca", type=int, default=-1)
        parser.add_argument("--hobiji", default="", help="Zarezom razdvojeno.")

    def handle(self, *args, persona, pokazi, actor, visina, tezina, deca, hobiji,
               **opts):
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"Persona {persona} ne postoji.")

        polja = {polje: opts[zastavica].strip()
                 for zastavica, polje in POLJA if opts[zastavica].strip()}
        if visina:
            polja["height_cm"] = visina
        if tezina:
            polja["weight_kg"] = tezina
        if deca >= 0:
            polja["children"] = deca
        if hobiji.strip():
            polja["hobbies"] = [h.strip() for h in hobiji.split(",") if h.strip()]

        if polja:
            if (opis := polja.get("appearance_prompt", "")):
                from apps.visuals import generator

                try:
                    generator.check_input(opis)
                except generator.ImageError as e:
                    raise CommandError(f"Opis izgleda odbijen: {e}") from e
            try:
                with bind(actor_id=actor):
                    d = org.set_dossier(p, actor=actor, **polja)
            except org.OrgError as e:
                raise CommandError(str(e)) from e
            self.stdout.write(self.style.SUCCESS(
                f"{p.public_id}: dosije v{d.dossier_version}, "
                f"upisano {len(polja)} polja."))
        if pokazi or not polja:
            self._pokazi(p)

    def _pokazi(self, p: Persona) -> None:
        d = org.dossier_of(p)
        if d is None:
            self.stdout.write("Dosije je prazan.")
            return
        red = [("mesto rođenja", d.birth_place), ("prebivalište", d.residence),
               ("visina", f"{d.height_cm} cm" if d.height_cm else ""),
               ("težina", f"{d.weight_kg} kg" if d.weight_kg else ""),
               ("građa", d.build), ("oči", d.eye_color), ("kosa", d.hair_color),
               ("frizura", d.hair_style), ("obeležja", d.distinguishing_marks),
               ("porodični status", d.marital_status),
               ("deca", str(d.children) if d.children else ""),
               ("hobiji", ", ".join(str(h) for h in (d.hobbies or [])))]
        self.stdout.write(f"\n{p.public_id} — {p.display_name}  (dosije v{d.dossier_version})")
        for ime, vrednost in red:
            if vrednost:
                self.stdout.write(f"  {ime:18} {vrednost}")

        odeljak = org.prompt_section(p)
        if odeljak:
            self.stdout.write("\n--- ide u sistemski prompt ---")
            self.stdout.write(odeljak)

        from apps.visuals import generator

        try:
            self.stdout.write("\n--- tekst za sliku (nalepi u generator) ---")
            self.stdout.write(generator.appearance_of(p))
        except generator.ImageError as e:
            self.stdout.write(self.style.WARNING(f"\nNema teksta za sliku: {e}"))
