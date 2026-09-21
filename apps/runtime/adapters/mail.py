"""Pošta. Canon §12.8 · Aneks A §6 · ADR-0008.

Pre slanja, i u dry-run-u:
  - primalac nije na centralnoj listi odjava (važi za SVE persone);
  - hladna pošta (`mail.send`) nikada sa primarnog domena kompanije;
  - najviše 3 aktivna mejlboksa po `sending_domain`-u;
  - dnevni plafon mejlboksa, sa zagrevanjem 5 → plafon u 21 dan.

Svaka poruka nosi `List-Unsubscribe` i `List-Unsubscribe-Post`
(RFC 8058, odjava jednim klikom) i From poravnat sa domenom slanja (DMARC).
"""

from __future__ import annotations

from datetime import timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from django.conf import settings

from apps.channels import suppression
from apps.channels.models import ChannelAccount
from apps.orchestration.models import Action
from apps.runtime.adapters.base import Adapter, Exec, Outcome, text_of
from apps.runtime.transport import Request
from common import enums as E

OC = E.ExecutionOutcome
R = E.RuntimeReason


def _domain_of(addr: str) -> str:
    return addr.strip().lower().rpartition("@")[2]


def is_primary_domain(domain: str) -> bool:
    d = domain.strip().lower().rstrip(".")
    for p in getattr(settings, "PRIMARY_COMPANY_DOMAINS", []):
        p = p.strip().lower()
        if p and (d == p or d.endswith("." + p)):
            return True
    return False


def mailbox_cap(acc: ChannelAccount, now) -> int:
    cap = acc.daily_cap or E.MAILBOX_DEFAULT_CAP
    if acc.warmup_started_at is None:
        return min(cap, E.MAILBOX_WARMUP_START)
    days = max(0, (now - acc.warmup_started_at).days)
    if days >= E.MAILBOX_WARMUP_DAYS:
        return cap
    ramp = E.MAILBOX_WARMUP_START + (cap - E.MAILBOX_WARMUP_START) * days / E.MAILBOX_WARMUP_DAYS
    return max(E.MAILBOX_WARMUP_START, int(ramp))


class MailAdapter(Adapter):
    key = "mail"

    def preflight(self, x: Exec) -> Outcome | None:
        acc, p, at = x.account, x.payload, x.action.action_type
        to = p.get("to")
        if not isinstance(to, str) or "@" not in to:
            return Outcome(OC.PERMANENT_ERROR, R.RECIPIENT_REQUIRED.value,
                           detail="Jedna poruka = jedan primalac (`to`).")
        if at == "mail.send" and suppression.is_suppressed(to):
            return Outcome(OC.DENIED_BY_POLICY, R.SUPPRESSED.value,
                           detail="Primalac je na centralnoj listi odjava.")
        domain = acc.sending_domain or (_domain_of(acc.persona_address)
                                        if at == "mail.reply" else "")
        if not domain:
            return Outcome(OC.NEEDS_HUMAN, R.SENDING_DOMAIN_MISSING.value,
                           detail="Mejlboks nema sending_domain.")
        if at == "mail.send" and is_primary_domain(domain):
            return Outcome(OC.DENIED_BY_POLICY, R.PRIMARY_DOMAIN_OUTBOUND.value,
                           detail="Hladna pošta nikada sa primarnog domena (Canon §12.8 t.1).")
        if acc.sending_domain:
            n = ChannelAccount.objects.filter(
                channel_type=E.ChannelType.EMAIL.value, sending_domain=acc.sending_domain,
                status=E.AccountStatus.ACTIVE.value).count()
            if n > E.MAX_MAILBOXES_PER_SENDING_DOMAIN:
                return Outcome(OC.DENIED_BY_POLICY, R.TOO_MANY_MAILBOXES.value,
                               detail=f"{n} aktivnih mejlbokseva na {acc.sending_domain}.")
        start = x.now - timedelta(hours=24)
        used = Action.objects.filter(
            channel_account=acc, action_type__in=["mail.send", "mail.reply"],
            status__in=[E.ActionStatus.SUCCEEDED.value, E.ActionStatus.RUNNING.value],
            started_at__gte=start).exclude(pk=x.action.pk).count()
        cap = mailbox_cap(acc, x.now)
        if used >= cap:
            return Outcome(OC.RETRYABLE_ERROR, R.MAILBOX_DAILY_CAP.value, retry_after_s=3600,
                           detail=f"{used}/{cap} u poslednja 24 h.")
        return None

    def message(self, x: Exec) -> EmailMessage:
        acc, p = x.account, x.payload
        domain = acc.sending_domain or _domain_of(acc.persona_address)
        local = (acc.persona_address or acc.handle).partition("@")[0] or "persona"
        msg = EmailMessage()
        msg["From"] = f"{x.action.persona.display_name} <{local}@{domain}>"
        if acc.persona_address:
            msg["Reply-To"] = acc.persona_address
        msg["To"] = p["to"]
        msg["Subject"] = str(p.get("subject") or "")[:250]
        msg["Date"] = format_datetime(x.now)
        msg["Message-ID"] = make_msgid(idstring=x.action.public_id, domain=domain)
        if p.get("in_reply_to"):
            msg["In-Reply-To"] = p["in_reply_to"]
            msg["References"] = p["in_reply_to"]
        unsub = suppression.unsubscribe_url(p["to"])
        msg["List-Unsubscribe"] = f"<{unsub}>, <mailto:unsubscribe@{domain}?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        sender = getattr(settings, "COMPANY_LEGAL_NAME", "") or domain
        footer = (f"\n\n--\nPošiljalac: {sender}\n"
                  f"Ako ne želite ove poruke, odjavite se: {unsub}\n")
        msg.set_content(text_of(p) + footer)
        return msg

    def perform(self, x: Exec) -> Outcome:
        msg = self.message(x)
        x.send(Request("SEND", f"smtp://{msg['From'].addresses[0].domain}", kind="smtp",
                       headers={"From": msg["From"].addresses[0].addr_spec, "To": msg["To"],
                                "Message-ID": msg["Message-ID"]},
                       body=msg.as_string()))
        return Outcome(OC.SUCCEEDED, R.DRY_RUN.value if x.dry else "OK",
                       external_ref=None if x.dry else msg["Message-ID"],
                       result={"message_id": msg["Message-ID"], "to_hash":
                               suppression.address_hash(msg["To"])})
