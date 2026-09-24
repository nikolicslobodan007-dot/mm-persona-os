"""Slika agenta iz komandne linije. ADR-0018.

    manage.py portrait --persona P-00001                 (profilna, jednom)
    manage.py portrait --persona P-00001 --force         (nova profilna)
    manage.py portrait --persona P-00001 --scene "u magacinu, pored paleta"
    manage.py portrait --persona P-00001 --show          (šta postoji)
    manage.py portrait --persona P-00001 --upload lik.png --kao-profilnu
    manage.py portrait --persona P-00001 --upload sajam.png --opis "na sajmu"

Generisanje ne radi dok je `IMAGE_ENABLED=false` i svaka generisana slika se
knjiži u troškove. **Otpremanje ručno napravljene slike radi uvek i ne košta
ništa** (ADR-0018, dopuna 24.09.).
"""

from __future__ import annotations

import pathlib

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.personas.models import Persona
from apps.visuals import generator


class Command(BaseCommand):
    help = "Pravi profilnu sliku ili sliku za galeriju."

    def add_arguments(self, parser):
        parser.add_argument("--persona", required=True)
        parser.add_argument("--scene", default="")
        parser.add_argument("--actor", default="user:slobodan")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--show", action="store_true")
        parser.add_argument("--upload", default="", help="Putanja do ručno napravljene slike.")
        parser.add_argument("--kao-profilnu", action="store_true", dest="kao_profilnu")
        parser.add_argument("--opis", default="", help="Opis slike za galeriju.")

    def handle(self, *args, persona, scene, actor, force, show, upload, kao_profilnu,
               opis, **opts):
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"Persona {persona} ne postoji.")
        if show:
            ref = generator.reference_of(p)
            self.stdout.write(f"Profilna: {ref.public_id if ref else '—'}")
            for a in generator.gallery_of(p):
                self.stdout.write(f"  {a.public_id}  {a.created_at:%d.%m %H:%M}  {a.kind}")
            return
        if not actor.startswith("user:"):
            raise CommandError("--actor mora biti čovek (user:…).")
        if upload:
            path = pathlib.Path(upload)
            if not path.is_file():
                raise CommandError(f"Nema fajla: {upload}")
            try:
                with bind(actor_id=actor):
                    r = generator.import_image(p, path.read_bytes(), actor=actor,
                                               as_portrait=kao_profilnu, label=opis)
            except generator.ImageError as e:
                raise CommandError(f"{e.code}: {e.detail}") from e
            self.stdout.write(self.style.SUCCESS(
                f"{r.asset.public_id} · {r.asset.kind} · otpremljeno, bez troška"))
            return
        try:
            with bind(actor_id=actor):
                r = (generator.make_photo(p, scene, actor=actor) if scene
                     else generator.make_portrait(p, actor=actor, force=force))
        except generator.ImageError as e:
            raise CommandError(f"{e.code}: {e.detail}") from e
        self.stdout.write(self.style.SUCCESS(
            f"{r.asset.public_id} · {r.asset.kind} · {r.model} · {r.cost_eur_cents} c"))
