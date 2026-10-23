"""Uvoz PDF-a u sloj znanja (ADR-0031, sloj 2).

Materijal donosi čovek (ADR-0074): izvor je `FIRST_PARTY_USER_INPUT`, licenca se
navodi (ADR-0059 §2 — `SLOBODNA` mora da imenuje licencu). Dedup po checksum-u
sadržaja. Sve (izvor + dokument + blokovi) ide u jednoj transakciji.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.libri.grind import grind
from apps.libri.models import Block, LibriDocument
from apps.memory.models import KnowledgeSource
from common import enums as E


class UvozError(Exception):
    """Uvoz se nije mogao izvršiti (nema fajla, loša licenca, duplikat, nema teksta)."""


def uvezi(path, *, naslov="", licenca="", naziv_licence=""):
    """Uveze jedan PDF → `KnowledgeSource` + `LibriDocument` + `Block`-ovi.

    Vraća napravljeni `LibriDocument`. Diže `UvozError` na svakoj grešci ulaza.
    """
    p = Path(path)
    if not p.is_file():
        raise UvozError(f"Fajl ne postoji: {path}")

    try:
        box = E.LicenseBox(licenca)
    except ValueError:
        dozvoljene = ", ".join(b.value for b in E.LicenseBox)
        raise UvozError(f"Nepoznata licenca {licenca!r}. Izbor: {dozvoljene}.") from None
    if box == E.LicenseBox.SLOBODNA and not naziv_licence.strip():
        raise UvozError("Licenca SLOBODNA mora da imenuje licencu (ADR-0059 §2).")

    checksum = hashlib.sha256(p.read_bytes()).hexdigest()
    postojeci = LibriDocument.objects.filter(checksum=checksum).first()
    if postojeci is not None:
        raise UvozError(
            f"Dokument sa istim sadržajem je već uvezen: {postojeci.document_id}."
        )

    meta, blokovi = grind(str(p), naslov=naslov or p.stem)
    if not blokovi:
        raise UvozError(
            "Iz PDF-a nije izvučen tekst (skeniran dokument? OCR nije u obimu sloja 2)."
        )

    with transaction.atomic():
        izvor = KnowledgeSource.objects.create(
            persona=None,
            source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT.value,
            title=meta["title"],
            trust_score=Decimal("1.000"),
            checksum=checksum,
            license_box=box.value,
            license_note=naziv_licence.strip(),
        )
        dok = LibriDocument.objects.create(
            source=izvor,
            document_id=meta["document_id"],
            version_id=meta["version_id"],
            title=meta["title"],
            language=meta["language"],
            script=meta["script"],
            pages=meta["pages"],
            checksum=checksum,
            running_headers_removed=meta["running_headers_removed"],
            ingested_at=timezone.now(),
        )
        Block.objects.bulk_create([
            Block(
                document=dok,
                block_id=b["block_id"],
                version_id=meta["version_id"],
                block_type=b["block_type"],
                text=b["text"],
                language=b["language"],
                order=b["order"],
                heading_path=b["heading_path"],
                source_page=b["source_page"],
                source_section=b["source_section"],
                extraction_confidence=Decimal(str(b["extraction_confidence"])),
                human_verified=b["human_verified"],
                previous_block_id=b["previous_block_id"],
                next_block_id=b["next_block_id"],
                parent_section_id=b["parent_section_id"],
            )
            for b in blokovi
        ])
    return dok
