"""Semantički vektori nad Libri blokovima (Block → BlockEmbedding).

ADR-0031 sloj 3. Isti model kao veštine (`VESTINA_EMBEDDING_MODEL`, MiniLM-L12,
simetričan — upit i blok se kodiraju isto, bez prefiksa) i ista dedup logika
(`text_hash`, Memory v0.1 §6) kao `apps/memory/znanje_vektori.py`. Vektor je
indeks za pronalaženje kandidata, nikad izvor istine (Canon §4.1).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from typing import Any

log = logging.getLogger(__name__)


def embeduj(blocks: Iterable[Any], *, model_key: str | None = None) -> dict[str, int]:
    """Napravi/osveži `BlockEmbedding` za date blokove (ADR-0031 sloj 3).

    Best-effort: ako semantički model nije dostupan (fastembed nije u slici ili
    model nije preuzet — offline), NE diže grešku, nego staje i vraća koliko je
    stiglo. Uvoz znanja ne sme da padne zbog modela (ADR-0009); pretraga pada na
    prazno dok vektora nema, a `libri reindeksiraj` ih dopuni kasnije.

    `text_hash` (Memory v0.1 §6): red sa istim modelom i istim tekstom se ne
    računa ponovo.
    """
    from apps.libri.models import BlockEmbedding
    from apps.memory import embeddings

    blocks = list(blocks)
    if not blocks:
        return {"upisano": 0, "preskoceno": 0}
    mk = model_key or embeddings.vestina_model_key()
    postojeci = {
        e.block_id: e.text_hash
        for e in BlockEmbedding.objects.filter(
            model_key=mk, block_id__in=[b.id for b in blocks]
        ).only("block_id", "text_hash")
    }
    upisano = 0
    preskoceno = 0
    for i, b in enumerate(blocks):
        tekst = b.text
        h = hashlib.sha256(f"{mk}\x00{tekst}".encode()).hexdigest()
        if postojeci.get(b.id) == h:
            preskoceno += 1
            continue
        try:
            vec = embeddings.embed_semanticki(tekst, model=mk)
        except Exception as e:  # noqa: BLE001 — model nedostupan: ne rušimo uvoz
            log.warning("embedovanje bloka stalo kod '%s' (model nedostupan): %s",
                        b.block_id, e)
            return {"upisano": upisano,
                    "preskoceno": preskoceno + (len(blocks) - i)}
        BlockEmbedding.objects.update_or_create(
            block=b, model_key=mk,
            defaults={"embedding": vec, "dimensions": len(vec), "text_hash": h})
        upisano += 1
    return {"upisano": upisano, "preskoceno": preskoceno}


def pretrazi(
    upit: str,
    *,
    top_k: int = 5,
    min_confidence: float = 0.6,
    model_key: str | None = None,
) -> list[tuple[Any, float]] | None:
    """Semantička pretraga blokova (ADR-0031 sloj 3).

    Vraća listu `(Block, udaljenost)` od najbližeg ka daljem (kosinus, manje =
    sličnije), ili `None` ako model nije dostupan (fastembed/offline) — tada
    pozivalac zna da semantika trenutno ne radi. Prazna lista znači da vektora
    nema ili da nijedan blok nije prošao filter.

    Filter: samo blokovi sa `perm_ai_read=True` i `extraction_confidence >=
    min_confidence` (odseca artefakte sa naslovne/ sadržaja iz sloja 2).
    """
    from pgvector.django import CosineDistance

    from apps.libri.models import BlockEmbedding
    from apps.memory import embeddings

    try:
        qv = embeddings.embed_semanticki(upit, model=model_key)
    except Exception as e:  # noqa: BLE001 — model nedostupan
        log.warning("semantička pretraga blokova pala (model nedostupan): %s", e)
        return None
    mk = model_key or embeddings.vestina_model_key()
    redovi = list(
        BlockEmbedding.objects
        .filter(
            model_key=mk,
            block__perm_ai_read=True,
            block__extraction_confidence__gte=min_confidence,
        )
        .annotate(dist=CosineDistance("embedding", qv))
        .order_by("dist")
        .select_related("block")[:top_k]
    )
    return [(e.block, float(e.dist)) for e in redovi]
