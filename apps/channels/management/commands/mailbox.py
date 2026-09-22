"""Sandučići persona na Mailcow-u (ADR-0015).

    manage.py mailbox status                     API i domen agenata
    manage.py mailbox plan    --persona P-00001  koja adresa bi bila (bez upisa)
    manage.py mailbox open    --persona P-00001  otvara sandučić (idempotentno)
    manage.py mailbox poll   [--persona P-00001] čita pristiglu poštu
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.channels import mailbox
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Sandučići persona na Mailcow-u."

    def add_arguments(self, parser):
        parser.add_argument("op", choices=["status", "plan", "open", "poll"])
        parser.add_argument("--persona")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, op, persona, actor, **opts):
        if op == "status":
            st = mailbox.mailcow_status()
            self.stdout.write(f"domen {mailbox.domain()} · {'OK' if st['ok'] else st['reason']}"
                              + (f" · {st.get('detail', '')}" if st.get("detail") else ""))
            return
        if op == "poll" and not persona:
            for addr, n in mailbox.poll_all().items():
                self.stdout.write(f"{addr}: {n}")
            return
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError("--persona P-xxxxx je obavezan i mora da postoji.")
        with bind(actor_id=actor):
            try:
                if op == "plan":
                    self.stdout.write(mailbox.address_for(p))
                elif op == "open":
                    acc = mailbox.provision(p, actor=actor)
                    self.stdout.write(f"Sandučić: {acc.persona_address}")
                else:
                    acc = mailbox.mailbox_of(p)
                    if acc is None:
                        raise CommandError("Persona nema sandučić.")
                    self.stdout.write(f"{acc.persona_address}: {mailbox.poll(acc)} novih")
            except mailbox.MailboxError as e:
                raise CommandError(f"{e.code}: {e.detail}") from e
