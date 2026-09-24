"""Sandučići persona na Mailcow-u (ADR-0015).

    manage.py mailbox status                     API i domen agenata
    manage.py mailbox plan    --persona P-00001  koja adresa bi bila (bez upisa)
    manage.py mailbox open    --persona P-00001  otvara sandučić (idempotentno)
    manage.py mailbox poll   [--persona P-00001] čita pristiglu poštu
    manage.py mailbox bez                        ko nema sandučić
    manage.py mailbox popuni                     otvara svima kojima fali
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.channels import mailbox
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Sandučići persona na Mailcow-u."

    def add_arguments(self, parser):
        parser.add_argument("op", choices=["status", "plan", "open", "poll",
                                          "bez", "popuni"])
        parser.add_argument("--persona")
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, op, persona, actor, **opts):
        if op == "status":
            st = mailbox.mailcow_status()
            self.stdout.write(f"domen {mailbox.domain()} · {'OK' if st['ok'] else st['reason']}"
                              + (f" · {st.get('detail', '')}" if st.get("detail") else ""))
            return
        if op in ("bez", "popuni"):
            return self._bez_sanducica(op == "popuni", actor)
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

    def _bez_sanducica(self, otvori: bool, actor: str) -> None:
        """Agenti kojima sandučić fali — i, po izboru, otvaranje za sve njih.

        Otvaranje jednog agenta može da padne (popunjena kvota domena), a to ne
        sme da sruši ostale: svaki se pokušava zasebno i razlog se ispisuje.
        """
        from common import enums as E

        fale = [p for p in Persona.objects.exclude(
            status__in=(E.PersonaStatus.ARCHIVED.value, E.PersonaStatus.SUSPENDED.value)
        ).order_by("public_id") if mailbox.mailbox_of(p) is None]
        if not fale:
            self.stdout.write("Svi agenti imaju sandučić.")
            return
        if not otvori:
            for p in fale:
                self.stdout.write(f"  {p.public_id} {p.display_name:28} "
                                  f"{mailbox.address_for(p)}")
            self.stdout.write(f"\nBez sandučića: {len(fale)}.")
            return
        otvoreno, palo = 0, []
        for p in fale:
            try:
                with bind(actor_id=actor):
                    acc = mailbox.provision(p, actor=actor)
            except mailbox.MailboxError as e:
                palo.append(f"{p.public_id}: {e}")
                continue
            otvoreno += 1
            self.stdout.write(self.style.SUCCESS(f"  {p.public_id} {acc.persona_address}"))
        for red in palo:
            self.stdout.write(self.style.WARNING(f"  {red}"))
        self.stdout.write(f"\nOtvoreno: {otvoreno}, nije uspelo: {len(palo)}.")
