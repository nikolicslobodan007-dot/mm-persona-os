"""Pojmovnik struke: domenska terminologija kao znanje i referenca sudiji.

Uz Pravopis (ADR-0055/0120), ovo je druga vrsta jezičkog znanja: STRUČNI termini
po domenima (vino, rakija, metrologija, …). Dve svrhe:
- sudija benchmarka (ADR-0154/0155) dobija relevantne termine kao referencu, pa
  ne obara tačne stručne reči („buke" je vinski termin, ne greška);
- agenti pišu tačnije kad imaju tačnu terminologiju.

Isti obrazac kao pravila Pravopisa: po jedan `KnowledgeSource` po izvoru (zbog
porekla), po jedna `KnowledgeFact` po terminu, `predicate="pojam.struke"`,
semantička pretraga preko istog sloja (`znanje_vektori`, ADR-0120). Pretraga ide
preko SVIH domena — domen je polje, ne zaseban izvor istine (ADR-0033).
"""
from __future__ import annotations

import json
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from api import audit
from apps.memory.models import KnowledgeFact, KnowledgeSource
from common import enums as E

PREDIKAT_POJMA = "pojam.struke"
_DATA = Path(__file__).resolve().parent / "data"

#: Izvori: naslov (ključ idempotentnog uvoza) → datoteka + poreklo. Vino/rakija
#: potvrdio praktičar (Kolibica); metrologija je VIML (DMDM, zvanično).
IZVORI = [
    {"naziv": "Pojmovnik — vino i rakija (WK, praktičar)",
     "datoteka": _DATA / "pojmovnik-vino-rakija.jsonl", "trust": 0.9},
    {"naziv": "Međunarodni rečnik termina u zakonskoj metrologiji (DMDM)",
     "datoteka": _DATA / "pojmovnik-metrologija.jsonl", "trust": 1.0},
]


def _subject(termin: str, domen: str) -> str:
    return f"{domen} — {termin}"[:220]


def uvezi(*, actor: str = "user:slobodan") -> dict[str, int]:
    """Uvozi SVE pojmovnike iz `IZVORI` u `KnowledgeSource`/`KnowledgeFact`.

    Isti obrazac kao `recnik.uvezi_pravila`: ponovni uvoz briše i upisuje ponovo
    (po izvoru), u transakciji. Embedovanje van transakcije, best-effort (ADR-0009).
    """
    sve_nove: list[KnowledgeFact] = []
    broj = {"upisano": 0, "obrisano": 0, "izvora": 0}
    with transaction.atomic():
        for iz in IZVORI:
            put: Path = iz["datoteka"]
            if not put.exists():
                continue
            redovi = [json.loads(r) for r in put.read_text(encoding="utf-8").splitlines() if r]
            izvor, _ = KnowledgeSource.objects.get_or_create(
                persona=None, title=iz["naziv"],
                defaults={"source_kind": E.SourceKind.FIRST_PARTY_USER_INPUT.value,
                          "trust_score": iz["trust"], "uri": "", "is_active": True})
            stare = KnowledgeFact.objects.filter(source=izvor, predicate=PREDIKAT_POJMA)
            broj["obrisano"] += stare.count()
            stare.delete()
            nove = KnowledgeFact.objects.bulk_create([
                KnowledgeFact(
                    source=izvor, persona=None,
                    subject=_subject(r["termin"], r.get("domen", "")),
                    predicate=PREDIKAT_POJMA,
                    provenance=E.Provenance.USER_PROVIDED.value, confidence=1.0,
                    object_json={"termin": r["termin"], "definicija": r.get("definicija", ""),
                                 "domen": r.get("domen", ""), "sinonimi": r.get("sinonimi", []),
                                 "izvor": r.get("izvor", "")})
                for r in redovi
            ], batch_size=1000)
            sve_nove += nove
            broj["upisano"] += len(redovi)
            broj["izvora"] += 1
            if redovi:
                izvor.ingested_at = timezone.now()
                izvor.save(update_fields=["ingested_at"])
    embedovano = embeduj_pojmove(sve_nove)
    audit.record("content.pojmovnik.loaded",
                 details={"actor": actor, **broj, "embedovano": embedovano["upisano"]})
    return broj


def _tekst_pojma_za_embedding(subject: str, object_json: dict) -> str:
    """Tekst termina za vektor: termin + sinonimi + definicija (isti i u uvozu i
    u pretrazi, da vektor predstavlja isti sadržaj — kao `_tekst_pravila...`)."""
    oj = object_json or {}
    termin = str(oj.get("termin") or "")
    sinonimi = " ".join(oj.get("sinonimi") or [])
    defin = str(oj.get("definicija") or "")
    glava = f"{termin} {sinonimi}".strip()
    return "\n".join(d for d in [glava, defin] if d).strip()


def embeduj_pojmove(facts, *, model_key: str | None = None) -> dict[str, int]:
    """Napravi/osveži `KnowledgeEmbedding` za date termine (ADR-0120). Best-effort."""
    from apps.memory import znanje_vektori

    return znanje_vektori.embeduj(
        facts, text_fn=_tekst_pojma_za_embedding, model_key=model_key)


def _rangiraj_pojmove(upit: str) -> list[KnowledgeFact]:
    """Termini poređani po smislu za upit (semantički; leksički fallback, ADR-0009)."""
    from apps.memory import embeddings, znanje_vektori

    base = list(
        KnowledgeFact.objects
        .filter(persona__isnull=True, predicate=PREDIKAT_POJMA, source__is_active=True)
        .select_related("source"))
    if upit.strip():
        sem = znanje_vektori.rang_fact_ids(upit, [f.id for f in base])
        if sem is not None:
            by_id = {f.id: f for f in base}
            poredak = [by_id[fid] for fid, _ in sem if fid in by_id]
            vidjeni = {fid for fid, _ in sem}
            poredak += [f for fid, f in by_id.items() if fid not in vidjeni]
            return poredak
    kw = embeddings.stems(upit) if upit.strip() else set()

    def kljuc(f: KnowledgeFact):
        oj = f.object_json or {}
        tekst = f"{oj.get('termin', '')} {oj.get('definicija', '')}"
        pogodak = len(kw & embeddings.stems(tekst)) if kw else 0
        return (-pogodak, f.subject)

    return sorted(base, key=kljuc)


def trazi_pojmove(upit: str, *, granica: int = 5) -> list[dict]:
    """Termini najbliži upitu po smislu. Prvih `granica`. Prazan upit → prazno."""
    if not upit.strip():
        return []
    poredak = _rangiraj_pojmove(upit)[:max(0, granica)]
    return [{"subject": f.subject, **(f.object_json or {})} for f in poredak]


def pojmovi_dostupni() -> bool:
    """Jesu li termini uopšte uvezeni (ADR-0033: prazno i neuvezeno nisu isto)."""
    return KnowledgeFact.objects.filter(
        persona__isnull=True, predicate=PREDIKAT_POJMA).exists()
