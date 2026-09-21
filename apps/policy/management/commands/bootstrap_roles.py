"""Šest uloga iz Canon §15.1 kao Django grupe, plus dozvola za odobrenja.

Idempotentno: pokreni posle svake migracije, ništa ne duplira. Ne dodeljuje
uloge korisnicima i ne pravi tokene — to se radi ručno (ADR-0004):

    python manage.py bootstrap_roles
    python manage.py createsuperuser            # ili postojeći korisnik
    python manage.py bootstrap_roles --grant slobodan system_admin
    python manage.py drf_create_token slobodan
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.policy.models import ApprovalRequest
from common import enums as E

#: Canon §15.1 — `reviewer` nije uloga nego ova dozvola.
DECIDE_CODENAME = "decide_approval"


class Command(BaseCommand):
    help = "Napravi grupe za šest Canon uloga i dozvolu policy.decide_approval."

    def add_arguments(self, parser):
        parser.add_argument("--grant", nargs=2, metavar=("USERNAME", "ROLE"),
                            help="Dodeli ulogu postojećem korisniku.")

    @transaction.atomic
    def handle(self, *args, grant=None, **opts):
        ct = ContentType.objects.get_for_model(ApprovalRequest)
        perm, _ = Permission.objects.get_or_create(
            content_type=ct, codename=DECIDE_CODENAME,
            defaults={"name": "Can decide approval requests"},
        )
        for role in E.Role:
            group, created = Group.objects.get_or_create(name=role.value)
            if role in E.APPROVAL_DECIDERS:
                group.permissions.add(perm)
            else:
                group.permissions.remove(perm)
            self.stdout.write(f"{'+' if created else '='} {role.value}")

        if grant:
            username, role_name = grant
            if role_name not in E.Role.values():
                raise CommandError(f"Nepoznata uloga {role_name!r}. Dozvoljene: {E.Role.values()}")
            user = get_user_model().objects.filter(username=username).first()
            if user is None:
                raise CommandError(f"Korisnik {username!r} ne postoji.")
            user.groups.add(Group.objects.get(name=role_name))
            self.stdout.write(f"{username} → {role_name}")
