"""Nacrt odgovora na pristiglu poštu (ADR-0016).

Kad agentu stigne poruka od čoveka, sistem napravi **nacrt odgovora** i
predloži akciju `mail.reply`. Odgovor čeka odobrenje u konzoli i, kao i sve
ostalo, ne izlazi napolje dok je `GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`.

Ne odgovara se na: automatske poruke (`Auto-Submitted`), liste (`List-Id`),
pošiljaoce tipa `noreply@`, poruke starije od `MAIL_REPLY_MAX_AGE_HOURS`, i na
istu poruku dvaput. Dnevni plafon je `MAIL_REPLIES_PER_DAY` po agentu.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from api import audit
from apps.channels.models import ChannelAccount, MailMessage
from common import enums as E

NO_REPLY = re.compile(r"(^|[.<])(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce)@",
                      re.I)
REPLIED = "reply_action"


def _address(raw: str) -> str:
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw or "")
    return m.group(0) if m else ""


def skip_reason(msg: MailMessage, *, now: datetime) -> str:
    meta = msg.metadata or {}
    if meta.get(REPLIED):
        return "ALREADY_REPLIED"
    if msg.direction != E.MailDirection.INBOUND.value:
        return "NOT_INBOUND"
    if meta.get("auto_submitted") and meta["auto_submitted"].lower() != "no":
        return "AUTO_SUBMITTED"
    if meta.get("list_id"):
        return "MAILING_LIST"
    sender = _address(msg.from_addr)
    if not sender or NO_REPLY.search(msg.from_addr or ""):
        return "NO_REPLY_SENDER"
    hours = getattr(settings, "MAIL_REPLY_MAX_AGE_HOURS", 72)
    if msg.received_at and msg.received_at < now - timedelta(hours=hours):
        return "TOO_OLD"
    if msg.persona.status not in (E.PersonaStatus.READY.value, E.PersonaStatus.ACTIVE.value):
        return f"PERSONA_{msg.persona.status}"
    return ""


def _system_prompt(persona) -> str:
    loc = persona.primary_locale
    jezik = "srpski, latinica, pravilna gramatika" if loc.lower().startswith("sr") else loc
    return "\n".join([
        f"Pišeš kao {persona.display_name}, AI persona. Ne tvrdi da si čovek.",
        "Odgovaraš na poslovni mejl. Kratko i konkretno, bez preuveličavanja.",
        "Brojke i rokove navodi samo ako ih znaš iz poruke ili iz svog znanja; "
        "ako nešto ne znaš, reci da proveravaš i pitaj tačno ono što ti treba.",
        "Ne obećavaj cenu, popust ni rok bez potvrde čoveka.",
        "Vrati samo telo poruke: bez naslova, bez svog potpisa i bez markdown-a.",
        "Tri do šest rečenica, oslovljavanje na 'Vi'.",
        f"Jezik: {jezik}.",
    ])


def subject_for(msg: MailMessage) -> str:
    s = (msg.subject or "").strip()
    return s[:250] if s.lower().startswith("re:") else f"Re: {s}"[:250]


def draft_reply(msg: MailMessage, *, now: datetime | None = None):
    """Vraća `Action` (čeka odobrenje) ili None ako se ne odgovara."""
    from apps.content.service import clean_generated
    from apps.llm_gateway import gateway
    from apps.memory import context as memory_context
    from apps.policy import guards
    from apps.policy import service as policy

    now = now or timezone.now()
    why = skip_reason(msg, now=now)
    if why:
        return None
    persona = msg.persona
    acc = ChannelAccount.objects.filter(pk=msg.channel_account_id).first()
    if acc is None or acc.status != E.AccountStatus.ACTIVE.value:
        return None
    cap = getattr(settings, "MAIL_REPLIES_PER_DAY", 5)
    from apps.orchestration.models import Action

    used = Action.objects.filter(persona=persona, action_type="mail.reply",
                                 created_at__gte=now - timedelta(days=1)).count()
    if used >= cap:
        audit.record("channel.mail.reply_skipped", persona=persona,
                     details={"reason": "DAILY_CAP", "used": used})
        return None

    from apps.content.service import operator_run

    run = operator_run(persona, now)
    query = f"{msg.subject}\n{msg.body_text[:500]}"
    pack = memory_context.build(persona, run, E.RetrievalProfile.REPLY_CONTEXT, query=query,
                                now=now)
    gen = gateway.generate(
        E.LLMPurpose.REPLY, _system_prompt(persona),
        f"{pack.text}\n\n## poruka na koju se odgovara\nOd: {msg.from_addr}\n"
        f"Naslov: {msg.subject}\n\n{msg.body_text[:4000]}\n\n## zadatak\nNapiši odgovor.",
        persona=persona, run=run, context_pack=pack.record, now=now,
        brief={"topic": msg.subject or "poruka", "language": persona.primary_locale})
    text = clean_generated(gen.text, persona) if gen.provider != gateway.LOCAL_PROVIDER \
        else gen.text
    payload = {"to": _address(msg.from_addr), "subject": subject_for(msg), "text": text,
               "in_reply_to": msg.provider_message_id, "mail_message_id": str(msg.id)}
    hits = guards.prohibitions("mail.reply", payload, "")
    if hits:
        audit.record("channel.mail.reply_skipped", persona=persona,
                     severity=E.AuditSeverity.WARNING,
                     details={"reason": f"HARD_PROHIBITION:{hits[0]}", "message": str(msg.id)})
        return None
    pr = policy.propose(persona, "mail.reply", payload, channel=acc, run=run,
                        intent=f"Odgovor na poruku {msg.provider_message_id}"[:200],
                        target_ref=payload["to"], now=now)
    with transaction.atomic():
        MailMessage.objects.filter(pk=msg.pk).update(
            metadata={**(msg.metadata or {}), REPLIED: pr.action.public_id})
    audit.record("channel.mail.reply_drafted", persona=persona,
                 details={"action": pr.action.public_id, "message": str(msg.id),
                          "status": pr.action.status, "provider": gen.provider})
    return pr.action


def draft_replies(messages, *, now: datetime | None = None) -> int:
    """Nacrti za novopristigle poruke. Greška jedne poruke ne ruši ostale."""
    if not getattr(settings, "MAIL_AUTOREPLY", True):
        return 0
    n = 0
    for m in messages:
        try:
            if draft_reply(m, now=now) is not None:
                n += 1
        except Exception:  # noqa: BLE001
            audit.record("channel.mail.reply_failed", persona=m.persona,
                         severity=E.AuditSeverity.WARNING, details={"message": str(m.id)})
    return n
