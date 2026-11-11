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
        return {"ok": True, "poruka": str(odgovor.id)}
    except nit_servis.RazgovorError as e:
        telegram.posalji_poruku(chat_id, f"Nisam mogla: {e}")
        return {"greska": str(e)}
