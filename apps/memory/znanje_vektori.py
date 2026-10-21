"""Semantički vektori nad bazom znanja (KnowledgeFact → KnowledgeEmbedding).

ADR-0120. Zajedničko mesto za dve vrste znanja koje se semantički pretražuju:
veštine (`apps/memory/vestine.py`, predikat `vestina.postupak`) i pravila
Pravopisa (`apps/content/recnik.py`, predikat `pravopis.pravilo`). Oba koriste
isti model (`VESTINA_EMBEDDING_MODEL`), istu tabelu (`KnowledgeEmbedding`) i
istu dedup logiku (Memory v0.1 §6) — pa logika stoji ovde jednom, a ne u
dva fajla.

Šta tačno od činjenice ulazi u vektor zna pozivalac: prosleđuje
`text_fn(subject, object_json) -> str`. Veština tamo šalje ime + koraci +
napomene, pravilo šalje odeljak + telo — vektor sadržaja, ne ceo zapis.

Vektor je indeks za pronalaženje kandidata, nikad izvor istine (Canon §4.1).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable
from typing import Any

log = logging.getLogger(__name__)


def embeduj(
    facts: Iterable[Any],
    *,
    text_fn: Callable[[str, dict], str],
    model_key: str | None = None,
) -> dict[str, int]:
    """Napravi/osveži `KnowledgeEmbedding` za date činjenice (ADR-0120).

    Best-effort: ako semantički model nije dostupan (fastembed nije instaliran
    ili model nije preuzet — offline), NE diže grešku, nego staje i vraća
    koliko je stiglo. Uvoz znanja ne sme da padne zbog modela (ADR-0009);
    rangiranje pada na leksičko dok vektora nema, a komanda za embedovanje ih
    dopuni kasnije.

    `text_hash` (Memory v0.1 §6): red sa istim modelom i istim tekstom se ne
    računa ponovo — ponovno embedovanje nad nepromenjenim korpusom je jeftino.
    """
    from apps.memory import embeddings
    from apps.memory.models import KnowledgeEmbedding

    facts = list(facts)
    if not facts:
        return {"upisano": 0, "preskoceno": 0}
    mk = model_key or embeddings.vestina_model_key()
    postojeci = {
        e.fact_id: e.text_hash
        for e in KnowledgeEmbedding.objects.filter(
            model_key=mk, fact_id__in=[f.id for f in facts]
        ).only("fact_id", "text_hash")
    }
    upisano = 0
    preskoceno = 0
    for i, f in enumerate(facts):
        tekst = text_fn(f.subject, f.object_json or {})
        h = hashlib.sha256(f"{mk}\x00{tekst}".encode()).hexdigest()
        if postojeci.get(f.id) == h:
            preskoceno += 1
            continue
        try:
            vec = embeddings.embed_semanticki(tekst, model=mk)
        except Exception as e:  # noqa: BLE001 — model nedostupan: ne rušimo uvoz
            log.warning("embedovanje stalo kod '%s' (model nedostupan): %s",
                        f.subject, e)
            return {"upisano": upisano,
                    "preskoceno": preskoceno + (len(facts) - i)}
        KnowledgeEmbedding.objects.update_or_create(
            fact=f, model_key=mk,
            defaults={"embedding": vec, "dimensions": len(vec), "text_hash": h})
        upisano += 1
    return {"upisano": upisano, "preskoceno": preskoceno}


def rang_fact_ids(
    query: str,
    fact_ids: Iterable[Any],
    *,
    model_key: str | None = None,
) -> list[tuple[Any, float]] | None:
    """Poređaj date činjenice po kosinusnoj sličnosti sa upitom (ADR-0120).

    Vraća listu `(fact_id, udaljenost)` od najbliže ka daljoj, ili `None` ako
    model nije dostupan (fastembed/offline) ili nijedna od datih činjenica još
    nema vektor — tada pozivalac pada na leksičko (ADR-0009). Udaljenost je
    kosinusna (manje = sličnije); pozivalac je može koristiti za prag.
    """
    from pgvector.django import CosineDistance

    from apps.memory import embeddings
    from apps.memory.models import KnowledgeEmbedding

    fact_ids = list(fact_ids)
    if not fact_ids:
        return None
    try:
        qv = embeddings.embed_semanticki(query)
    except Exception as e:  # noqa: BLE001 — model nedostupan: leksički fallback
        log.warning("semantički rang pao, leksički fallback: %s", e)
        return None
    mk = model_key or embeddings.vestina_model_key()
    poredak = list(
        KnowledgeEmbedding.objects
        .filter(model_key=mk, fact_id__in=fact_ids)
        .annotate(dist=CosineDistance("embedding", qv))
        .order_by("dist")
        .values_list("fact_id", "dist"))
    return poredak or None
