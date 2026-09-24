"""Sandučić persone na sopstvenom Mailcow serveru (ADR-0015).

Svaka persona dobija adresu na domenu agenata (`AGENT_MAIL_DOMAIN`, npr.
`mila.vukovic@webkorporacija.com`). Sandučić otvara sistem preko Mailcow
REST API-ja; pristigla pošta se čita preko IMAP-a i čuva kao `MailMessage`.

Tajne:
  - Mailcow API ključ je samo u `.env.prod` (`MAILCOW_CREDENTIAL`, `env:`/`file:`);
  - lozinka sandučića se NIGDE ne čuva — izvodi se iz `MAILBOX_PASSWORD_CREDENTIAL`
    i javnog ID-ja persone (HMAC), isto kao TOTP u konzoli (ADR-0010).

Ovaj modul ne šalje poštu. Slanje ide kroz `mail.reply`/`mail.send` akcije,
policy, odobrenje i obe brave (ADR-0007, ADR-0008). Hladna pošta sa ovog
domena je i dalje zabranjena (Canon §12.8 t.1) — adresa persone je za
primanje i odgovore.
"""

from __future__ import annotations

import base64
import email
import email.header
import email.policy
import email.utils
import hashlib
import hmac
import imaplib
import json
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from api import audit
from apps.channels.models import ChannelAccount, MailMessage
from apps.personas.models import Persona
from common import enums as E

MAILBOX_REF = "derived:mailbox:v1"
#: Sandučić agenta sme da odgovara na primljenu poštu; slanje i dalje traži
#: odobrenje, poverenje L2 i otključan globalni prekidač (ADR-0016).
REPLY_CAPABILITY = "email.reply_inbound"
_TRANSLIT = str.maketrans({"đ": "dj", "Đ": "Dj", "ß": "ss"})


class MailboxError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def enabled() -> bool:
    return bool(getattr(settings, "MAILCOW_ENABLED", False)
                and getattr(settings, "MAILCOW_URL", ""))


def domain() -> str:
    return getattr(settings, "AGENT_MAIL_DOMAIN", "webkorporacija.com").strip().lower()


# ---------------------------------------------------------------- adresa i lozinka


def local_part(persona: Persona) -> str:
    """„Mila Vuković (AI)” → `mila.vukovic`. Samo a–z, 0–9, tačka."""
    name = re.sub(r"\(.*?\)", "", persona.display_name).translate(_TRANSLIT)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    parts = re.findall(r"[a-z0-9]+", name.lower())
    return ".".join(parts)[:48] or persona.public_id.lower().replace("-", "")


def address_for(persona: Persona) -> str:
    """Slobodna adresa. Isto ime kod druge persone → dodaje se broj iz ID-ja."""
    acc = mailbox_of(persona)
    if acc is not None:
        return acc.persona_address
    base = f"{local_part(persona)}@{domain()}"
    taken = ChannelAccount.objects.filter(
        channel_type=E.ChannelType.EMAIL.value, persona_address=base).exclude(persona=persona)
    if not taken.exists():
        return base
    num = persona.public_id.split("-")[-1].lstrip("0") or "0"
    return f"{local_part(persona)}.{num}@{domain()}"


def _secret() -> bytes:
    from apps.runtime.transport import CredentialMissing, resolve_secret

    try:
        return resolve_secret(settings.MAILBOX_PASSWORD_CREDENTIAL).strip().encode()
    except CredentialMissing as e:
        raise MailboxError("CREDENTIAL_MISSING", "MAILBOX_PASSWORD_SECRET") from e


def password_for(persona: Persona, version: int = 1) -> str:
    """Izvedena lozinka — ista svaki put, nigde upisana. Zadovoljava Mailcow politiku."""
    mac = hmac.new(_secret(), f"mailbox:{persona.public_id}:v{version}".encode(),
                   hashlib.sha256).digest()
    body = base64.urlsafe_b64encode(mac).decode().rstrip("=")[:28]
    return f"Wk-{body}-9a"


def mailbox_of(persona: Persona) -> ChannelAccount | None:
    return (ChannelAccount.objects.filter(persona=persona,
                                          channel_type=E.ChannelType.EMAIL.value)
            .exclude(persona_address="").filter(credential_ref=MAILBOX_REF).first())


# ---------------------------------------------------------------- Mailcow API


def _api(path: str, body: dict | None = None) -> object:
    from apps.runtime.transport import CredentialMissing, resolve_secret

    try:
        key = resolve_secret(settings.MAILCOW_CREDENTIAL).strip()
    except CredentialMissing as e:
        raise MailboxError("CREDENTIAL_MISSING", "MAILCOW_API_KEY") from e
    url = settings.MAILCOW_URL.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"X-API-Key": key, "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        raise MailboxError(f"HTTP_{e.code}", e.read().decode(errors="replace")[:200]) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MailboxError("NETWORK", str(e)[:200]) from e


def _mailcow_ok(resp: object) -> tuple[bool, str]:
    """Mailcow vraća listu {type: success|danger|error, msg: [...]}."""
    items = resp if isinstance(resp, list) else [resp]
    msgs = []
    for it in items:
        if not isinstance(it, dict):
            continue
        msg = json.dumps(it.get("msg", ""), ensure_ascii=False)
        msgs.append(msg)
        if it.get("type") == "success":
            return True, msg
        if "object_exists" in msg or "mailbox_exists" in msg:
            return True, msg
    return False, "; ".join(msgs)[:300]


def mailcow_status() -> dict:
    """Za konzolu i proveru: da li API odgovara i da li domen postoji."""
    if not enabled():
        return {"ok": False, "reason": "MAILCOW_DISABLED"}
    try:
        d = _api(f"/api/v1/get/domain/{domain()}")
    except MailboxError as e:
        return {"ok": False, "reason": e.code, "detail": e.detail}
    exists = isinstance(d, dict) and bool(d.get("domain_name") or d.get("domain"))
    return {"ok": exists, "reason": "" if exists else "DOMAIN_NOT_IN_MAILCOW"}


# ---------------------------------------------------------------- otvaranje


@transaction.atomic
def provision(persona: Persona, *, actor: str) -> ChannelAccount:
    """Otvara sandučić (idempotentno). Bez `MAILCOW_ENABLED` — greška, ništa se ne upisuje."""
    existing = mailbox_of(persona)
    if existing is not None:
        return existing
    if persona.status in (E.PersonaStatus.ARCHIVED.value, E.PersonaStatus.SUSPENDED.value):
        raise MailboxError("VALIDATION_ERROR", f"Persona je {persona.status}.")
    if not enabled():
        raise MailboxError("MAILCOW_DISABLED", "MAILCOW_ENABLED=false ili nema MAILCOW_URL.")
    addr = address_for(persona)
    local, _, dom = addr.partition("@")
    pw = password_for(persona)
    ok, msg = _mailcow_ok(_api("/api/v1/add/mailbox", {
        "local_part": local, "domain": dom, "name": persona.display_name,
        "quota": str(getattr(settings, "MAILBOX_QUOTA_MB", 1024)),
        "password": pw, "password2": pw, "active": "1", "force_pw_update": "0",
        "tls_enforce_in": "1", "tls_enforce_out": "1"}))
    if not ok:
        # Najčešći razlog na domenu sa mnogo agenata je popunjena kvota domena,
        # a Mailcow to kaže nejasno. Prevodimo u rečenicu koja kaže šta da radiš.
        if "quota" in msg.lower() or "kvot" in msg.lower():
            raise MailboxError(
                "MAILCOW_QUOTA",
                f"Domen {dom} je popunjen: nema mesta za još jedan sandučić od "
                f"{getattr(settings, 'MAILBOX_QUOTA_MB', 200)} MB. Podigni kvotu "
                "domena u Mailcow-u ili smanji MAILBOX_QUOTA_MB.")
        raise MailboxError("MAILCOW_REJECTED", msg)
    try:
        acc = ChannelAccount.objects.create(
            persona=persona, channel_type=E.ChannelType.EMAIL.value,
            identity_vehicle=E.IdentityVehicle.NEWSLETTER.value, handle=addr,
            persona_address=addr, status=E.AccountStatus.ACTIVE.value,
            disclosure_label_status=E.DisclosureLabelStatus.NOT_REQUIRED.value,
            disclosure_text=persona.display_name, credential_ref=MAILBOX_REF,
            last_verified_at=timezone.now())
    except IntegrityError as e:
        raise MailboxError("VERSION_CONFLICT", str(e)[:200]) from e
    from apps.channels.models import ChannelCapability

    ChannelCapability.objects.update_or_create(
        account=acc, capability=REPLY_CAPABILITY,
        defaults={"is_enabled": True, "source": "api",
                  "evidence_level": E.EvidenceLevel.RESPONSE_ONLY.value,
                  "verified_at": timezone.now()})
    audit.record("channel.mailbox.provisioned", persona=persona,
                 details={"address": addr, "actor": actor})
    return acc


def deactivate(persona: Persona, *, actor: str) -> ChannelAccount | None:
    """Gasi sandučić (arhiviran agent). Poruke ostaju, prijava više ne radi."""
    acc = mailbox_of(persona)
    if acc is None:
        return None
    if enabled():
        _mailcow_ok(_api("/api/v1/edit/mailbox",
                         {"items": [acc.persona_address], "attr": {"active": "0"}}))
    acc.status = E.AccountStatus.REVOKED.value
    acc.save(update_fields=["status", "updated_at"])
    audit.record("channel.mailbox.deactivated", persona=persona,
                 severity=E.AuditSeverity.WARNING,
                 details={"address": acc.persona_address, "actor": actor})
    return acc


# ---------------------------------------------------------------- čitanje


def _decode(value: str | None) -> str:
    if not value:
        return ""
    return str(email.header.make_header(email.header.decode_header(value)))[:998]


def _text_of(msg: email.message.Message) -> str:
    part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else msg
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, KeyError, ValueError):
        text = (part.get_payload(decode=True) or b"").decode(errors="replace")
    if part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()[:20000]


def store_inbound(acc: ChannelAccount, raw: bytes, now: datetime) -> MailMessage | None:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    mid = (msg.get("Message-ID") or "").strip() or "sha256:" + hashlib.sha256(raw).hexdigest()
    if MailMessage.objects.filter(channel_account=acc, provider_message_id=mid[:220]).exists():
        return None
    try:
        received = email.utils.parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else now
    except (TypeError, ValueError):
        received = now
    days = getattr(settings, "MAIL_BODY_RETENTION_DAYS", 90)
    m = MailMessage.objects.create(
        persona=acc.persona, channel_account=acc, direction=E.MailDirection.INBOUND.value,
        provider_message_id=mid[:220], thread_key=(msg.get("References") or mid).split()[0][:220],
        in_reply_to=(msg.get("In-Reply-To") or "")[:220],
        from_addr=_decode(msg.get("From"))[:320],
        to_addrs=[a for _, a in email.utils.getaddresses(msg.get_all("To", []))][:20],
        cc_addrs=[a for _, a in email.utils.getaddresses(msg.get_all("Cc", []))][:20],
        subject=_decode(msg.get("Subject")), body_text=_text_of(msg),
        body_retained_until=now + timedelta(days=days), received_at=received,
        metadata={"auto_submitted": msg.get("Auto-Submitted", ""),
                  "list_id": _decode(msg.get("List-Id"))[:200]})
    return m


def poll(acc: ChannelAccount, *, now: datetime | None = None, limit: int = 50) -> int:
    """Čita nepročitanu poštu (IMAP). Poruke ostaju na serveru, označene kao pročitane."""
    now = now or timezone.now()
    host = getattr(settings, "MAILCOW_IMAP_HOST", "") or re.sub(
        r"^https?://", "", settings.MAILCOW_URL).split("/")[0]
    n = 0
    fresh: list[MailMessage] = []
    with imaplib.IMAP4_SSL(host, 993, timeout=30) as imap:
        imap.login(acc.persona_address, password_for(acc.persona))
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for num in (data[0].split() if data and data[0] else [])[:limit]:
            _, parts = imap.fetch(num, "(RFC822)")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
            m = store_inbound(acc, raw, now) if raw else None
            if m is not None:
                fresh.append(m)
                n += 1
    if n:
        audit.record("channel.mail.received", persona=acc.persona,
                     details={"account": acc.persona_address, "count": n})
    if fresh:
        from apps.channels import reply

        reply.draft_replies(fresh, now=now)
    return n


def poll_all() -> dict[str, int | str]:
    if not enabled():
        return {}
    out: dict[str, int | str] = {}
    for acc in ChannelAccount.objects.filter(
            channel_type=E.ChannelType.EMAIL.value, credential_ref=MAILBOX_REF,
            status=E.AccountStatus.ACTIVE.value).select_related("persona"):
        try:
            out[acc.persona_address] = poll(acc)
        except (OSError, imaplib.IMAP4.error, MailboxError) as e:
            out[acc.persona_address] = f"ERR {type(e).__name__}"
    return out
