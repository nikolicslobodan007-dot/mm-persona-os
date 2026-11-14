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
def telegram_odgovori(chat_id, telo: str, actor: str,
                      foto_file_id: str | None = None, foto_mime: str = "") -> dict:
    """ADR-0134/0118 — čovekova Telegram poruka (tekst i/ili slika) → posao →
    Ivanin odgovor nazad. Ceo lanac ide kroz `razgovor.posalji()`, pod proverenim
    `actor`-om. Slika (ako je ima) se skine, sačuva kao MediaAsset i prosledi kao
    vizuelni prilog (ADR-0118) — isto kao prilog iz konzole."""
    from apps.channels import telegram
    from apps.orchestration import razgovor as nit_servis

    nit = telegram.nit_za(actor)
    if nit is None:
        telegram.posalji_poruku(chat_id, "Nema direktora (DIR-00) — javi Slobodanu.")
        return {"nit": False}
    media, prilozi = _slikovni_prilog(nit.persona, foto_file_id, foto_mime, actor)
    try:
        with bind(actor_id=actor):
            odgovor = nit_servis.posalji(nit, telo, actor=actor,
                                         prilozi=prilozi, media=media)
        telegram.posalji_poruku(chat_id, odgovor.telo)
        _mozda_dokument(chat_id, odgovor)
        return {"ok": True, "poruka": str(odgovor.id), "slika": bool(media)}
    except nit_servis.RazgovorError as e:
        telegram.posalji_poruku(chat_id, f"Nisam mogla: {e}")
        return {"greska": str(e)}


def _slikovni_prilog(direktor, foto_file_id, foto_mime, actor):
    """Skine Telegram sliku i sačuva je kao MediaAsset (ADR-0118), isto kao
    konzola (`_obradi_priloge`). Vraća (media, prilozi); prazno kad slike nema
    ili skidanje padne — odgovor tada ide samo na tekst (ne ruši se)."""
    if not foto_file_id:
        return [], []
    import logging

    from apps.channels import telegram
    from apps.content.dokument import next_sequence
    from apps.visuals import storage
    from apps.visuals.models import MediaAsset
    from common import enums as E
    from common import ids as I

    skinuto = telegram.preuzmi_sliku(foto_file_id, foto_mime)
    if skinuto is None:
        return [], []
    podaci, mime, naziv = skinuto
    try:
        digest = storage.sha256(podaci)
        kljuc = storage.key_for(direktor.public_id, digest, mime)
        storage.put(podaci, key=kljuc, mime=mime)
        # Ista slika poslata ponovo = isti (sadržajni) ključ: iskoristi postojeći
        # asset, ne pravi duplikat (UNIQUE storage_key bi oborio ceo odgovor). ADR-0118.
        asset = MediaAsset.objects.filter(storage_key=kljuc).first()
        if asset is None:
            asset = MediaAsset.objects.create(
                public_id=I.media_asset_public_id(direktor.public_id,
                                                  next_sequence(direktor)),
                persona=direktor, kind=E.AssetKind.PHOTO.value, storage_key=kljuc,
                mime_type=mime, sha256=digest, origin="user_owned",
                rights_note=f"Telegram prilog; primila {direktor.public_id}; akter {actor}.")
    except Exception as e:  # noqa: BLE001 — slika je dodatak, ne ruši odgovor
        logging.getLogger(__name__).warning("telegram slika nije sačuvana: %s", e)
        return [], []
    media = [{"asset": asset, "naziv": naziv, "mime": mime}]
    prilozi = [{"vrsta": "fajl", "naziv": naziv, "asset": asset}]
    return media, prilozi


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
