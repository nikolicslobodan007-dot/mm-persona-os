"""Uvoz dolazne poruke (MailMessage) u sloj znanja (ADR-0031 §4, sloj 2).

Dolazna pošta već stiže u bazu kao `MailMessage` (IMAP `mailbox.poll`). Ovde se
JEDNA označena poruka pretvara u `KnowledgeSource` + `LibriDocument` + `Block`-ove,
isti cevovod kao PDF/web uvoz. Čovek bira koju poruku uvozi (ADR-0074) — nema
bulk/automatskog uvoza, da se kontroliše koji lični podaci ulaze u bazu znanja.

Poverenje: `FIRST_PARTY_USER_INPUT` sa trust 0.5 — čovek donosi materijal, ali je
sadržaj TUĐA (pošiljaočeva) tvrdnja, ne proverena istina, zato < first-party 1.0.
Poreklo (Message-ID, pošiljalac) ide u `uri`/`license_note` radi sledljivosti.
Injekcija u telu ne menja ponašanje: tvrdnje su OBSERVED, deterministička osnova
ne izvršava uputstva iz teksta (Canon §10.4).
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.libri import uvoz_web
from apps.libri.models import Block, LibriDocument
from apps.libri.uvoz import UvozError
from apps.memory.models import KnowledgeSource
from common import enums as E

VERSION_ID = "v1"
TRUST_MAIL = Decimal("0.500")  # tuđa tvrdnja, ne proverena istina (< first-party 1.0)

_PARA = re.compile(r"\n\s*\n")
_WS = re.compile(r"\s+")


def naslov_i_blokovi(naslov: str, telo: str) -> tuple[list[dict], str, str]:
    """(blokovi, lang, script) iz naslova + tela poruke. Čista funkcija (bez baze)."""
    naslov = (naslov or "").strip()
    full = (naslov + " " + (telo or ""))[:5000]
    lang, script = uvoz_web._skript_jezik(full)

    delovi: list[tuple[str, str]] = []
    if naslov:
        delovi.append(("heading", naslov))
    for para in _PARA.split(telo or ""):
        t = _WS.sub(" ", para).strip()
        if t and uvoz_web._znacajan(t):
            delovi.append(("paragraph", t))

    blocks: list[dict] = []
    heading_path = [naslov[:220]] if naslov else []
    for tag, text in delovi:
        je_naslov = tag == "heading"
        if je_naslov:
            heading_path = [text[:220]]
        blocks.append({
            "block_id": f"blk_{len(blocks) + 1:06d}",
            "block_type": "heading" if je_naslov else "paragraph",
            "text": text, "language": lang, "order": len(blocks) + 1,
            "heading_path": list(heading_path),
            "source_page": None,
            "source_section": (heading_path[-1][:220] if heading_path else ""),
            "extraction_confidence": 0.5 if je_naslov else 0.7,
            "human_verified": False,
        })
    for i, b in enumerate(blocks):
        b["previous_block_id"] = blocks[i - 1]["block_id"] if i > 0 else ""
        b["next_block_id"] = blocks[i + 1]["block_id"] if i + 1 < len(blocks) else ""
        b["parent_section_id"] = ""
    return blocks, lang, script


def ugradi_poruku(mm, *, licenca="", naziv_licence="") -> LibriDocument:
    """Pretvori jednu `MailMessage` u Libri izvor + dokument + blokove."""
    try:
        box = E.LicenseBox(licenca)
    except ValueError:
        dozvoljene = ", ".join(b.value for b in E.LicenseBox)
        raise UvozError(f"Nepoznata licenca {licenca!r}. Izbor: {dozvoljene}.") from None
    if box == E.LicenseBox.SLOBODNA and not naziv_licence.strip():
        raise UvozError("Licenca SLOBODNA mora da imenuje licencu (ADR-0059 §2).")

    naslov = (mm.subject or "").strip()
    telo = mm.body_text or ""
    sadrzaj = f"{naslov}\n{telo}"
    checksum = hashlib.sha256(sadrzaj.encode("utf-8", "replace")).hexdigest()
    postojeci = LibriDocument.objects.filter(checksum=checksum).first()
    if postojeci is not None:
        raise UvozError(f"Sadržaj je već uvezen: {postojeci.document_id}.")

    blokovi, lang, script = naslov_i_blokovi(naslov, telo)
    if not blokovi:
        raise UvozError("Poruka nema iskoristivog teksta (prazno telo i naslov).")
    title = (naslov or f"Poruka od {mm.from_addr}")[:300]

    with transaction.atomic():
        izvor = KnowledgeSource.objects.create(
            persona=None,
            source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
            title=title,
            uri=f"mailmsg:{mm.provider_message_id}"[:500],
            trust_score=TRUST_MAIL,
            checksum=checksum,
            license_box=box.value,
            license_note=(naziv_licence.strip() or f"od: {mm.from_addr}")[:500],
        )
        dok = LibriDocument.objects.create(
            source=izvor,
            document_id="mail_" + checksum[:12],
            version_id=VERSION_ID,
            title=title,
            language=lang,
            script=script,
            pages=1,
            checksum=checksum,
            ingested_at=timezone.now(),
        )
        Block.objects.bulk_create([
            Block(
                document=dok, block_id=b["block_id"], version_id=VERSION_ID,
                block_type=b["block_type"], text=b["text"], language=b["language"],
                order=b["order"], heading_path=b["heading_path"],
                source_page=b["source_page"], source_section=b["source_section"],
                extraction_confidence=Decimal(str(b["extraction_confidence"])),
                human_verified=b["human_verified"],
                previous_block_id=b["previous_block_id"],
                next_block_id=b["next_block_id"], parent_section_id=b["parent_section_id"],
            )
            for b in blokovi
        ])

    from apps.libri import vektori
    vektori.embeduj(dok.blocks.all())
    return dok
