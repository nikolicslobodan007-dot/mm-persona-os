"""Propisi: zakoni i podzakonska akta kao izvor u bazi znanja.

Treći sloj jezičkog/činjeničkog znanja uz Pravopis (ADR-0055/0120) i Pojmovnik
struke (ADR-0156). Ovde je sadržaj PRAVNI: po jedan zapis za svaki član propisa,
sa doslovnim tekstom (verno), glavom i naslovom člana. Dve svrhe:
- agenti i persone citiraju TAČAN član umesto da parafraziraju po sećanju;
- semantička pretraga (ADR-0120) nalazi relevantan član po smislu upita.

Isti obrazac kao Pojmovnik: po jedan `KnowledgeSource` po propisu (zbog porekla
i idempotentnog uvoza), po jedna `KnowledgeFact` po članu, `predicate="propis.clan"`,
pretraga preko istog vektorskog sloja (`znanje_vektori`).

NAMERNO BEZ auto-sudije usaglašenosti: ovaj modul je IZVOR (čita, nalazi, citira),
ne presuđuje da li je nešto „u skladu sa zakonom". Pravna ocena je ljudski posao.

Masovno prikupljanje propisa (skidanje sirovih dokumenata sa zvaničnog izvora,
po listi prioriteta, dnevni ritam) je posao farm-agenta — ovaj modul je ono u
šta agent pakuje ono što skine: original ostaje, a članovi postaju pretraživi.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from api import audit
from apps.memory.models import KnowledgeFact, KnowledgeSource
from common import enums as E

PREDIKAT_CLANA = "propis.clan"
_DATA = Path(__file__).resolve().parent / "data"

#: Izvori: naslov (ključ idempotentnog uvoza) → datoteka + poreklo. Zakon je javni
#: akt; `sl_glasnik` u svakom redu je zvanična referenca (merodavna, ne komercijalni
#: preprodavac). `trust=1.0` jer je tekst doslovan iz službenog glasnika.
IZVORI = [
    {"naziv": "Zakon o metrologiji (Sl. glasnik RS, br. 15/2016)",
     "datoteka": _DATA / "propisi-zakon-o-metrologiji.jsonl", "trust": 1.0},
]


def _subject(propis: str, clan: int, naslov: str) -> str:
    rep = f"{propis} — Član {clan}"
    if naslov:
        rep += f" ({naslov})"
    return rep[:220]


def uvezi(*, actor: str = "user:slobodan") -> dict[str, int]:
    """Uvozi SVE propise iz `IZVORI` u `KnowledgeSource`/`KnowledgeFact`.

    Isti obrazac kao `pojmovnik.uvezi`: ponovni uvoz briše i upisuje ponovo (po
    propisu), u transakciji. Embedovanje van transakcije, best-effort (ADR-0009).
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
            stare = KnowledgeFact.objects.filter(source=izvor, predicate=PREDIKAT_CLANA)
            broj["obrisano"] += stare.count()
            stare.delete()
            nove = KnowledgeFact.objects.bulk_create([
                KnowledgeFact(
                    source=izvor, persona=None,
                    subject=_subject(r["propis"], r["clan"], r.get("naslov", "")),
                    predicate=PREDIKAT_CLANA,
                    provenance=E.Provenance.USER_PROVIDED.value, confidence=1.0,
                    object_json={"propis": r["propis"], "sl_glasnik": r.get("sl_glasnik", ""),
                                 "glava": r.get("glava", ""), "clan": r["clan"],
                                 "naslov": r.get("naslov", ""), "tekst": r.get("tekst", "")})
                for r in redovi
            ], batch_size=1000)
            sve_nove += nove
            broj["upisano"] += len(redovi)
            broj["izvora"] += 1
            if redovi:
                izvor.ingested_at = timezone.now()
                izvor.save(update_fields=["ingested_at"])
    embedovano = embeduj_clanove(sve_nove)
    audit.record("content.propisi.loaded",
                 details={"actor": actor, **broj, "embedovano": embedovano["upisano"]})
    return broj


def _tekst_clana_za_embedding(subject: str, object_json: dict) -> str:
    """Tekst člana za vektor: naslov + tekst (isti i u uvozu i u pretrazi, da
    vektor predstavlja isti sadržaj — kao `_tekst_pojma_za_embedding`)."""
    oj = object_json or {}
    naslov = str(oj.get("naslov") or "")
    tekst = str(oj.get("tekst") or "")
    return "\n".join(d for d in [naslov, tekst] if d).strip()


def embeduj_clanove(facts, *, model_key: str | None = None) -> dict[str, int]:
    """Napravi/osveži `KnowledgeEmbedding` za date članove (ADR-0120). Best-effort."""
    from apps.memory import znanje_vektori

    return znanje_vektori.embeduj(
        facts, text_fn=_tekst_clana_za_embedding, model_key=model_key)


def _baza_qs(propis: str | None = None):
    qs = (KnowledgeFact.objects
          .filter(persona__isnull=True, predicate=PREDIKAT_CLANA, source__is_active=True)
          .select_related("source"))
    if propis:
        qs = qs.filter(object_json__propis=propis)
    return qs


def _rangiraj_clanove(upit: str, *, propis: str | None = None) -> list[KnowledgeFact]:
    """Članovi poređani po smislu za upit (semantički; leksički fallback, ADR-0009)."""
    from apps.memory import embeddings, znanje_vektori

    base = list(_baza_qs(propis))
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
        tekst = f"{oj.get('naslov', '')} {oj.get('tekst', '')}"
        pogodak = len(kw & embeddings.stems(tekst)) if kw else 0
        return (-pogodak, oj.get("clan", 0))

    return sorted(base, key=kljuc)


_BROJ_CLANA = re.compile(r"\bčlan(?:a|u|om)?\s+(\d{1,3})\b", re.IGNORECASE)


def _broj_iz_upita(upit: str) -> int | None:
    """Ako upit imenuje član („član 26", „po članu 44") → broj tog člana."""
    m = _BROJ_CLANA.search(upit or "")
    return int(m.group(1)) if m else None


def clan(broj: int, *, propis: str | None = None) -> dict | None:
    """Vrati tačno određen član po broju (i opciono po propisu). Bez pretrage."""
    f = _baza_qs(propis).filter(object_json__clan=broj).first()
    return {"subject": f.subject, **(f.object_json or {})} if f else None


def trazi_clanove(upit: str, *, granica: int = 5, propis: str | None = None) -> list[dict]:
    """Članovi relevantni za upit. Prazan upit → prazno.

    Ako upit imenuje broj člana („član 26") — taj član ide PRVI (egzaktno), pa se
    dopuni semantički (po smislu, ADR-0120) do `granica`.
    """
    if not upit.strip():
        return []
    poredak: list[KnowledgeFact] = []
    vidjeni: set[int] = set()
    broj = _broj_iz_upita(upit)
    if broj is not None:
        f = _baza_qs(propis).filter(object_json__clan=broj).first()
        if f:
            poredak.append(f)
            vidjeni.add(f.id)
    for f in _rangiraj_clanove(upit, propis=propis):
        if len(poredak) >= granica:
            break
        if f.id not in vidjeni:
            poredak.append(f)
            vidjeni.add(f.id)
    return [{"subject": f.subject, **(f.object_json or {})} for f in poredak[:granica]]


def propisi_dostupni() -> bool:
    """Jesu li članovi uopšte uvezeni (ADR-0033: prazno i neuvezeno nisu isto)."""
    return KnowledgeFact.objects.filter(
        persona__isnull=True, predicate=PREDIKAT_CLANA).exists()
