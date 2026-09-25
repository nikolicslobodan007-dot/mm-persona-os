"""Nalog poslušnika. ADR-0039 §1.

    manage.py poslusnik --napravi --u /etc/mm-persona-os/runner.env
    manage.py poslusnik --stanje

Token se **ne ispisuje na ekran.** Slobodan slika terminal, a ključ na slici je
ključ u tuđim rukama — isto pravilo kao za ključeve agenata (ADR-0026). Upisuje
se u fajl 0600, a na ekran ide samo putanja i poslednja četiri znaka.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError

from api.base import RUNNER_GROUP, SERVICE_PREFIX

IME = f"{SERVICE_PREFIX}runner"


class Command(BaseCommand):
    help = "Pravi ili obnavlja nalog poslušnika (ADR-0039)."

    def add_arguments(self, parser):
        parser.add_argument("--napravi", action="store_true")
        parser.add_argument("--stanje", action="store_true")
        parser.add_argument("--u", default="", help="Fajl u koji ide PERSONA_TOKEN.")

    def handle(self, *args, napravi, stanje, u, **opts):
        from rest_framework.authtoken.models import Token

        if stanje == napravi:
            raise CommandError("Treba tačno jedno: --napravi ili --stanje.")

        korisnik = User.objects.filter(username=IME).first()
        if stanje:
            if korisnik is None:
                self.stdout.write("Poslušnik nije napravljen.")
                return
            grupe = sorted(korisnik.groups.values_list("name", flat=True))
            t = Token.objects.filter(user=korisnik).first()
            self.stdout.write(f"{IME} · grupe: {', '.join(grupe) or 'nijedna'}")
            self.stdout.write(f"  token: {'…' + t.key[-4:] if t else 'nema'}")
            self.stdout.write("  vidi samo: /tasks/queued, /tasks/{id}/work, "
                              "/tasks/{id}/gate")
            return

        if not u:
            raise CommandError("Treba --u putanja: token se ne ispisuje na ekran.")
        put = Path(u)
        if not put.parent.exists():
            raise CommandError(f"Direktorijum {put.parent} ne postoji.")

        if korisnik is None:
            korisnik = User.objects.create_user(username=IME)
            korisnik.set_unusable_password()   # prijava samo tokenom
            korisnik.save()
        grupa, _ = Group.objects.get_or_create(name=RUNNER_GROUP)
        korisnik.groups.set([grupa])           # nijedna Canon uloga, samo ova grupa

        Token.objects.filter(user=korisnik).delete()
        token = Token.objects.create(user=korisnik)

        put.write_text(f"PERSONA_TOKEN={token.key}\n", encoding="utf-8")
        os.chmod(put, 0o600)
        self.stdout.write(self.style.SUCCESS(f"{IME} spreman."))
        self.stdout.write(f"  token upisan u {put} (0600), završava se na …{token.key[-4:]}")
        self.stdout.write("  Stari token je poništen — ako je poslušnik radio, restartuj ga.")
