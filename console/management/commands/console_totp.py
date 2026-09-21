"""Uključi ili rotiraj drugi faktor za konzolu.

    python manage.py console_totp --user slobodan            prvi put
    python manage.py console_totp --user slobodan --rotate   novi ključ (stari prestaje)

Ispisuje ključ za ručni unos u aplikaciju (Google Authenticator, Microsoft
Authenticator, 1Password, Aegis…) i otpauth:// adresu. Pokreće se samo na
serveru — ključ se nikad ne prikazuje u pregledaču ni ne čuva u bazi.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from console import totp
from console.models import OperatorTOTP


class Command(BaseCommand):
    help = "Drugi faktor (TOTP) za kontrolnu tablu."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True)
        parser.add_argument("--rotate", action="store_true")

    def handle(self, *args, user, rotate, **opts):
        u = get_user_model().objects.filter(username=user, is_active=True).first()
        if u is None:
            raise CommandError(f"Korisnik {user} ne postoji ili nije aktivan.")
        rec, created = OperatorTOTP.objects.get_or_create(user=u)
        if rotate and not created:
            rec.version += 1
            rec.confirmed_at, rec.last_step = None, 0
            rec.save()
        key = totp.b32(totp.secret_for(u.get_username(), rec.version))
        grouped = " ".join(key[i:i + 4] for i in range(0, len(key), 4))
        self.stdout.write(f"Korisnik: {u.get_username()} (verzija ključa {rec.version})")
        self.stdout.write(f"Ključ za ručni unos: {grouped}")
        self.stdout.write("Vrsta: vremenski (TOTP), 6 cifara, 30 s")
        self.stdout.write(f"otpauth: {totp.provisioning_uri(u.get_username(), rec.version)}")
