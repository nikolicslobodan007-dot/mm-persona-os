"""Celery taskovi kanala. ADR-0015.

    channels.mail_poll      beat 120 s, `mail` — pristigla pošta persona (IMAP)
"""

from __future__ import annotations

from api.context import bind
from apps.channels import mailbox
from config.celery import app


@app.task(name="channels.mail_poll")
def mail_poll() -> dict:
    with bind(actor_id="service:mail-poll"):
        return mailbox.poll_all()


@app.task(name="channels.telegram_poll")
def telegram_poll() -> dict:
    """ADR-0134 — pokupi Telegram poruke i zakaži odgovore. Beat, `mail`."""
    from apps.channels import telegram

    return telegram.obradi_batch()


@app.task(name="channels.telegram_odgovori")
def telegram_odgovori(chat_id, telo: str, actor: str) -> dict:
    """ADR-0134 — jedna čovekova Telegram poruka → posao → Ivanin odgovor nazad.
    Ceo lanac ide kroz `razgovor.posalji()`, pod proverenim `actor`-om."""
    from apps.channels import telegram
    from apps.orchestration import razgovor as nit_servis

    nit = telegram.nit_za(actor)
    if nit is None:
        telegram.posalji_poruku(chat_id, "Nema direktora (DIR-00) — javi Slobodanu.")
        return {"nit": False}
    try:
        with bind(actor_id=actor):
            odgovor = nit_servis.posalji(nit, telo, actor=actor)
        telegram.posalji_poruku(chat_id, odgovor.telo)
        _mozda_dokument(chat_id, odgovor)
        return {"ok": True, "poruka": str(odgovor.id)}
    except nit_servis.RazgovorError as e:
        telegram.posalji_poruku(chat_id, f"Nisam mogla: {e}")
        return {"greska": str(e)}


def _mozda_dokument(chat_id, odgovor) -> None:
    """ADR-0147 — dug sadržaj (članak/newsletter) ide i kao PDF fajl na Telegram.

    Fajl je dodatak uz tekst; svaki pad (nema LibreOffice, skladište, mreža) se
    guta i odgovor ostaje poslat. Kratki formati (objava, nit) ne idu kao fajl.
    """
    import logging

    from apps.channels import telegram
    from apps.content import dokument
    from apps.content.models import ContentItem
    from apps.visuals import storage
    from common import enums as E

    dugi = {E.ContentFormat.ARTICLE.value, E.ContentFormat.NEWSLETTER.value}
    delovi = getattr(odgovor, "delovi", None) or {}
    # PDF ide SAMO kad je posao prošao (ADR-0147/0148). Odbijen/zastao nacrt se
    # ne šalje kao uredan fajl — to bi obmanulo („nije urađeno" pa PDF).
    if delovi.get("stanje") != "uradjeno":
        return
    kljuc = delovi.get("item")
    if not kljuc:
        return
    item = ContentItem.objects.filter(pk=kljuc).first()
    if item is None or item.format not in dugi:
        return
    try:
        asset = dokument.napravi(item, oblik="pdf", actor="service:telegram")
        podaci = storage.get(asset.storage_key)
    except Exception as e:  # noqa: BLE001 — PDF je dodatak, ne ruši odgovor
        logging.getLogger(__name__).warning("telegram PDF pao: %s", e)
        return
    naziv = ((item.title or "dokument").strip()[:60] or "dokument") + ".pdf"
    telegram.posalji_dokument(chat_id, podaci, naziv)
