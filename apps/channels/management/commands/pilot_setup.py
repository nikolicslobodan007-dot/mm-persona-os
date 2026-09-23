"""Priprema persone za pilot u SIMULATION: sandbox sme da prima nacrte objava.

    python manage.py pilot_setup --persona P-00001 --actor user:slobodan

Šta radi (idempotentno):
  - na SANDBOX nalogu persone uključuje `content.publish_approved`;
  - podiže poverenje za `content.publish_approved` na L1 (razlog i ko je to
    uradio ostaju u audit-u — ovo je odluka čoveka, zato `--actor` je obavezan).

Ne dira nijedan stvarni kanal i ne menja `GLOBAL_EXTERNAL_ACTIONS_ENABLED`.
Svaka objava i dalje traži odobrenje (A2).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.channels.models import ChannelAccount, ChannelCapability
from apps.personas.models import Persona
from apps.policy import config, service
from common import enums as E

CAP = "content.publish_approved"


class Command(BaseCommand):
    help = "Sandbox kanal persone spreman za nacrte objava (pilot, SIMULATION)."

    def add_arguments(self, parser):
        parser.add_argument("--persona", required=True)
        parser.add_argument("--actor", required=True, help="npr. user:slobodan")
        parser.add_argument("--reason", default="Pilot A: objave samo na sandbox, uz odobrenje")
        parser.add_argument("--with-mail", action="store_true",
                            help="uz to: odgovaranje na poštu (email.reply_inbound, L2)")

    def handle(self, *args, persona, actor, reason, with_mail=False, **opts):
        if not actor.startswith("user:"):
            raise CommandError("--actor mora biti čovek (user:…).")
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"Persona {persona} ne postoji.")
        acc = ChannelAccount.objects.filter(persona=p,
                                            channel_type=E.ChannelType.SANDBOX.value).first()
        if acc is None:
            raise CommandError("Persona nema SANDBOX nalog (pokreni seed).")
        _, created = ChannelCapability.objects.update_or_create(
            account=acc, capability=CAP,
            defaults={"is_enabled": True, "source": "manual",
                      "evidence_level": E.EvidenceLevel.RESPONSE_ONLY})
        level = service.trust_map(p).get(CAP, E.TrustLevel.L0)
        if not config.trust_at_least(level, E.TrustLevel.L1):
            with bind(actor_id=actor):
                service.change_trust(p, CAP, E.TrustLevel.L1, actor=actor, reason=reason)
            level = E.TrustLevel.L1
        if with_mail:
            from apps.channels import mailbox

            box = mailbox.mailbox_of(p)
            if box is None:
                raise CommandError("Persona nema sandučić (mailbox open).")
            ChannelCapability.objects.update_or_create(
                account=box, capability=mailbox.REPLY_CAPABILITY,
                defaults={"is_enabled": True, "source": "manual",
                          "evidence_level": E.EvidenceLevel.RESPONSE_ONLY})
            lvl = service.trust_map(p).get(mailbox.REPLY_CAPABILITY, E.TrustLevel.L0)
            if not config.trust_at_least(lvl, E.TrustLevel.L2):
                with bind(actor_id=actor):
                    service.change_trust(p, mailbox.REPLY_CAPABILITY, E.TrustLevel.L2,
                                         actor=actor, reason=reason)
            self.stdout.write(f"{p.public_id} · {box.persona_address}: "
                              f"{mailbox.REPLY_CAPABILITY} uključen; poverenje L2.")
        self.stdout.write(f"{p.public_id} · {acc.handle}: {CAP} "
                          f"{'uključen' if created else 'već uključen'}; poverenje {level.value}; "
                          f"okruženje {p.runtime_environment}.")
