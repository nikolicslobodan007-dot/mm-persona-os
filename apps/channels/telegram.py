"""Telegram — druga ulazna vrata firme (pored konzole). ADR-0134.

Čovek piše Ivani (direktor, DIR-00) sa telefona; most prosleđuje poruku kroz
`razgovor.posalji()` — isti mozak kao konzola. INTERNO je: ti ↔ tvoj agent, kao
konzola; ne dira prekidač spoljnih radnji i NIJE „agenti objavljuju javno".

Bezbednost: bot odgovara SAMO Telegram ID-evima iz `TELEGRAM_ALLOWED_IDS`
(allowlist), mapiranim na `user:slobodan`. Svaka druga poruka se tiho ignoriše.
Token se čita iz tajne (`TELEGRAM_TOKEN_CREDENTIAL`), ne stoji u kodu.

v1: polling (Celery beat), async odgovor, samo tekst. Webhook i prilozi kasnije.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
import uuid

from django.conf import settings

from apps.runtime.transport import CredentialMissing, resolve_secret

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{metod}"
OFFSET_KEY = "telegram:offset"
LOCK_KEY = "telegram:poll:lock"
MAX_PORUKA = 4000


def omogucen() -> bool:
    return bool(getattr(settings, "TELEGRAM_ENABLED", False))


def _token() -> str | None:
    try:
        return resolve_secret(settings.TELEGRAM_TOKEN_CREDENTIAL).strip()
    except CredentialMissing:
        return None


def dozvoljeni() -> set[str]:
    sirovo = getattr(settings, "TELEGRAM_ALLOWED_IDS", "") or ""
    return {d.strip() for d in sirovo.split(",") if d.strip()}


def actor_za(chat_id) -> str | None:
    """Mapiranje Telegram ID → actor. v1: svaki dozvoljeni ID je vlasnik."""
    return "user:slobodan" if str(chat_id) in dozvoljeni() else None


def _redis():
    import redis
    return redis.from_url(settings.CELERY_BROKER_URL)


def _api(token: str, metod: str, params: dict, timeout: int = 10) -> dict:
    url = API.format(token=token, metod=metod)
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001 — mreža/Telegram pao: ne ruši poll
        log.warning("telegram %s pao: %s", metod, e)
        return {}


def posalji_poruku(chat_id, tekst: str) -> None:
    token = _token()
    if not token:
        return
    _api(token, "sendMessage", {"chat_id": chat_id, "text": (tekst or "")[:MAX_PORUKA]})


def posalji_dokument(chat_id, podaci: bytes, naziv: str, opis: str = "") -> None:
    """ADR-0147 — pošalji fajl (PDF) na Telegram preko sendDocument (multipart).

    Mreža/Telegram pad se guta (kao i kod poruke): fajl je dodatak, ne sme da
    obori odgovor koji je već poslat kao tekst.
    """
    token = _token()
    if not token or not podaci:
        return
    granica = "----mmwk" + uuid.uuid4().hex
    delovi: list[bytes] = []
    for ime, vrednost in (("chat_id", str(chat_id)), ("caption", (opis or "")[:1000])):
        delovi.append(
            (f'--{granica}\r\nContent-Disposition: form-data; name="{ime}"'
             f'\r\n\r\n{vrednost}\r\n').encode())
    delovi.append(
        (f'--{granica}\r\nContent-Disposition: form-data; name="document"; '
         f'filename="{naziv}"\r\nContent-Type: application/pdf\r\n\r\n').encode()
        + podaci + b"\r\n")
    delovi.append(f"--{granica}--\r\n".encode())
    telo = b"".join(delovi)
    url = API.format(token=token, metod="sendDocument")
    req = urllib.request.Request(
        url, data=telo, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={granica}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001 — fajl je dodatak, ne ruši odgovor
        log.warning("telegram sendDocument pao: %s", e)


def nit_za(actor: str):
    """Najnovija nit vlasnika ili nova sa DIR-00 direktorom (kao konzola)."""
    from apps.orchestration.models import Razgovor
    from apps.personas.models import Assignment

    nit = (Razgovor.objects.filter(human_owner=actor)
           .order_by("-updated_at").first())
    if nit is not None:
        return nit
    a = (Assignment.objects.filter(position__code="DIR-00", ended_at__isnull=True,
                                   is_primary=True).select_related("persona").first())
    if a is None:
        return None
    return Razgovor.objects.create(persona=a.persona, human_owner=actor,
                                   naslov="Razgovor sa direktorom (Telegram)")


def obradi_batch() -> dict:
    """Jedan ciklus: pokupi nove poruke, potvrdi dozvoljene, zakaži odgovor.

    Ne radi sam posao — to je `channels.telegram_odgovori`. Jedan poll u isto
    vreme (redis lock), da se poruka ne obradi dvaput. Offset u redisu da se
    stare poruke ne ponavljaju posle restarta.
    """
    if not omogucen():
        return {"off": True}
    token = _token()
    if not token:
        return {"token": False}
    r = _redis()
    if not r.set(LOCK_KEY, "1", nx=True, ex=8):
        return {"zakljucano": True}
    try:
        offset = int(r.get(OFFSET_KEY) or 0)
        data = _api(token, "getUpdates",
                    {"offset": offset, "timeout": 0, "limit": 20}, timeout=15)
        updates = data.get("result") or []
        from apps.channels.tasks import telegram_odgovori

        zakazano = 0
        for u in updates:
            offset = max(offset, int(u["update_id"]) + 1)
            msg = u.get("message") or u.get("edited_message") or {}
            chat_id = (msg.get("chat") or {}).get("id")
            telo = (msg.get("text") or "").strip()
            actor = actor_za(chat_id)
            if not actor or not telo:
                continue  # nepoznat ID ili bez teksta → tiho preskoči
            posalji_poruku(chat_id, "Primila sam, radim na tome…")
            telegram_odgovori.delay(chat_id, telo, actor)
            zakazano += 1
        r.set(OFFSET_KEY, offset)
        return {"procitano": len(updates), "zakazano": zakazano}
    finally:
        r.delete(LOCK_KEY)
