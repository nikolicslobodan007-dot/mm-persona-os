"""Nacrt odgovora na pristiglu poštu (ADR-0016).

Kad agentu stigne poruka od čoveka, sistem napravi **nacrt odgovora** i
predloži akciju `mail.reply`. Odgovor čeka odobrenje u konzoli i, kao i sve
ostalo, ne izlazi napolje dok je `GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`.

Ne odgovara se na: automatske poruke (`Auto-Submitted`), liste (`List-Id`),
pošiljaoce tipa `noreply@`, poruke starije od `MAIL_REPLY_MAX_AGE_HOURS`, i na
istu poruku dvaput. Dnevni plafon je `MAIL_REPLIES_PER_DAY` po agentu.

ADR-0021: odgovor je **plan od dva koraka** — „napiši" pa „pošalji uz
odobrenje". Drugi korak pauzira plan dok čovek ne odluči; odobrenje ga
nastavlja, odbijanje ga zaustavlja i upisuje razlog.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from api import audit
from apps.channels.models import ChannelAccount, MailMessage
from apps.orchestration import plans
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


def _compose(msg: MailMessage, now: datetime) -> str:
    """Tekst odgovora — memorija, radno mesto, model, čišćenje. Bez spoljnog efekta."""
    from apps.content.service import clean_generated, operator_run
    from apps.llm_gateway import gateway
    from apps.memory import context as memory_context
    from apps.personas.org import prompt_section as org_section

    persona = msg.persona
    run = operator_run(persona, now)
    query = f"{msg.subject}\n{msg.body_text[:500]}"
    pack = memory_context.build(persona, run, E.RetrievalProfile.REPLY_CONTEXT, query=query,
                                now=now)
    who = org_section(persona, now=now)
    gen = gateway.generate(
        E.LLMPurpose.REPLY, _system_prompt(persona),
        (f"{who}\n\n" if who else "")
        + f"{pack.text}\n\n## poruka na koju se odgovara\nOd: {msg.from_addr}\n"
        f"Naslov: {msg.subject}\n\n{msg.body_text[:4000]}\n\n## zadatak\nNapiši odgovor.",
        persona=persona, run=run, context_pack=pack.record, now=now,
        brief={"topic": msg.subject or "poruka", "language": persona.primary_locale})
    return (clean_generated(gen.text, persona) if gen.provider != gateway.LOCAL_PROVIDER
            else gen.text)


@plans.handler("mail.draft")
def _step_draft(step, state) -> plans.Outcome:
    """Korak 1 — napiši odgovor. Ništa ne izlazi napolje."""
    msg = MailMessage.objects.filter(pk=step.input_json.get("message")).first()
    if msg is None:
        return plans.Failed("Poruka više ne postoji.")
    now = timezone.now()
    text = _compose(msg, now)
    if not text.strip():
        return plans.Failed("Model nije vratio tekst.")
    return plans.Done({"text": text, "to": _address(msg.from_addr),
                       "subject": subject_for(msg),
                       "in_reply_to": msg.provider_message_id,
                       "mail_message_id": str(msg.id)})


@plans.handler("mail.send")
def _step_send(step, state) -> plans.Outcome:
    """Korak 2 — predloži slanje. Čeka čoveka; ništa ne izlazi bez odobrenja."""
    from apps.policy import guards
    from apps.policy import service as policy

    drafts = state.get("by_handler", {}).get("mail.draft") or []
    if not drafts:
        return plans.Failed("Nema nacrta iz prethodnog koraka.")
    payload = {k: drafts[-1][k] for k in
               ("to", "subject", "text", "in_reply_to", "mail_message_id")}
    persona = step.plan.persona
    msg = MailMessage.objects.filter(pk=payload["mail_message_id"]).first()
    acc = ChannelAccount.objects.filter(pk=msg.channel_account_id).first() if msg else None
    if acc is None or acc.status != E.AccountStatus.ACTIVE.value:
        return plans.Failed("Sandučić više nije aktivan.")
    hits = guards.prohibitions("mail.reply", payload, "")
    if hits:
        return plans.Failed(f"Tvrda zabrana: {hits[0]}")
    pr = policy.propose(persona, "mail.reply", payload, channel=acc, run=step.plan.run,
                        plan_step=step, intent=f"Odgovor na {payload['in_reply_to']}"[:200],
                        target_ref=payload["to"])
    action = pr.action
    audit.record("channel.mail.reply_drafted", persona=persona,
                 details={"action": action.public_id, "message": payload["mail_message_id"],
                          "status": action.status, "plan": step.plan.public_id})
    if action.status == E.ActionStatus.APPROVAL_PENDING:
        return plans.Waiting(action, note="Odgovor čeka odobrenje.")
    return plans.Done({"action": action.public_id, "status": action.status})


def draft_reply(msg: MailMessage, *, now: datetime | None = None):
    """Pravi plan „napiši pa pošalji" i vraća akciju koja čeka odobrenje.

    ADR-0021: odgovor više nije usamljena akcija nego korak plana, pa odluka
    čoveka nastavlja ili zaustavlja zadatak — i u oba slučaja ostaje zapisano.
    """
    from apps.orchestration.models import Action

    now = now or timezone.now()
    if skip_reason(msg, now=now):
        return None
    persona = msg.persona
    acc = ChannelAccount.objects.filter(pk=msg.channel_account_id).first()
    if acc is None or acc.status != E.AccountStatus.ACTIVE.value:
        return None
    cap = getattr(settings, "MAIL_REPLIES_PER_DAY", 5)
    used = Action.objects.filter(persona=persona, action_type="mail.reply",
                                 created_at__gte=now - timedelta(days=1)).count()
    if used >= cap:
        audit.record("channel.mail.reply_skipped", persona=persona,
                     details={"reason": "DAILY_CAP", "used": used})
        return None

    plan = plans.start(persona, f"Odgovor na poruku: {msg.subject or '(bez naslova)'}"[:200],
                       [{"handler": "mail.draft", "type": E.StepType.CREATE.value,
                         "description": "Napiši odgovor", "input": {"message": str(msg.id)}},
                        {"handler": "mail.send", "type": E.StepType.ACTION.value,
                         "description": "Pošalji odgovor (uz odobrenje)"}],
                       actor="service:mail-poll", now=now)
    plans.advance(plan, now=now)

    waiting = plan.steps.filter(status=E.StepStatus.RUNNING.value).first()
    ref = (waiting.output_json or {}).get("waiting_for") if waiting else None
    if ref is None:
        last = plan.steps.filter(status=E.StepStatus.DONE.value).order_by("-sequence").first()
        ref = (last.output_json or {}).get("action") if last else None
    action = Action.objects.filter(public_id=ref).first() if ref else None
    if action is not None:
        with transaction.atomic():
            MailMessage.objects.filter(pk=msg.pk).update(
                metadata={**(msg.metadata or {}), REPLIED: action.public_id})
    return action


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
