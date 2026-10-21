"""Context Builder. Memory v0.1 §12; Canon §1, §10.4, §16.3.

    pack = build(persona, run, RetrievalProfile.DAILY_PLANNER, query="…")

Pravi najmanji skup informacija za jednu odluku i beleži TAČNO šta je
ušlo (`MemoryContextPack`: ID-jevi, skorovi, hash). Tekst se ne čuva u
paketu — rekonstruiše se iz memorija i poredi sa hash-om.

Pravila iz §12.2 koja se ovde sprovode, ne preporučuju:
  - zamenjene (SUPERSEDED) tvrdnje nikad ne ulaze;
  - sporne (otvorena protivrečnost) ulaze samo sa oznakom „⚠ sporno";
  - izvod (`inferred`) ulazi sa oznakom „izvod, ne činjenica" (Canon §10.4);
  - osetljivo ulazi samo za dozvoljenu svrhu (filter je u retrieval-u);
  - tvrdi plafon tokena se nikad ne prelazi — višak se odseca i beleži.

ADR-0096 — pored memorije persone, paket nosi i odeljak `vestine`: kućno
znanje koje je čovek doneo i odobrio (ADR-0074), iz baze znanja
(`KnowledgeFact`, predikat `vestina.postupak`). Ulaze samo veštine čiji je
izvor aktivan i čija je kutija licence tačno `SLOBODNA` (ADR-0059) — provera
ide OVDE, pri sastavljanju paketa, ne pri uvozu, jer se licenca izvora može
promeniti posle uvoza (ADR-0095). Veštine imaju SVOJ plafon
(`PROFILE_VESTINE_TOKENS`) koji se dodaje POVRH plafona memorije — ne smeju
da joj oduzmu prostor.

Procena tokena je ⌈znakova / 4⌉ — gruba, ali konzervativna za latinicu.
Pravi tokenizer dolazi sa LLM gateway-om.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import math
import pathlib
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.behaviour.models import BehaviourState
from apps.memory import embeddings, retrieval
from apps.memory.models import KnowledgeFact, MemoryContextPack, MemoryItem
from apps.memory.vestine import PREDIKAT as VESTINA_PREDIKAT
from apps.observability import bus
from apps.personas.models import Assignment, Biography, TraitProfile
from common import enums as E

log = logging.getLogger(__name__)

#: Memory v0.1 §12 — fiksni deo konteksta pored memorije.
CORE_OVERHEAD_TOKENS = 1500

#: ADR-0112 — koliko veština ulazi U CELINI (sa koracima). Ostale iz budžeta
#: idu kao indeks (ime + čemu služe), da agent zna ceo svoj alat a ne samo
#: prve tri. Broj je postavljen rukom i menja se ADR-om kad merenje kaže.
VESTINE_PUNIH = 4
POLICY_LINES = (
    "Spoljne akcije nisu dozvoljene bez odluke Policy engine-a (Canon §6.2).",
    "AI priroda persone se nikad ne skriva (Canon §9.4).",
    "Izvod (inferred) nije činjenica i ne ide u javni izlaz (Canon §10.4).",
)


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


@dataclass
class Pack:
    record: MemoryContextPack
    text: str
    sections: dict[str, str]
    items: list[retrieval.Scored] = field(default_factory=list)


def _core(persona) -> str:
    bio = Biography.objects.filter(persona=persona).first()
    traits = TraitProfile.objects.filter(persona=persona).first()
    lines = [f"{persona.display_name} [{persona.public_id}] — AI persona; oznaka je obavezna.",
             f"Jezik {persona.primary_locale}, vremenska zona {persona.timezone}."]
    if bio:
        lines.append(bio.headline or bio.short_bio[:300])
    if traits:
        top = sorted(((f, getattr(traits, f)) for f in (
            "openness", "conscientiousness", "extraversion", "curiosity",
            "evidence_preference", "risk_tolerance")), key=lambda x: -x[1])[:4]
        lines.append("Izražene osobine: " + ", ".join(f"{k} {v}" for k, v in top))
    return "\n".join(lines)


def _state(persona) -> str:
    s = BehaviourState.objects.filter(persona=persona).first()
    if not s:
        return ""
    return (f"energija {s.energy}, raspoloženje {s.valence}, fokus {s.focus}, "
            f"opterećenje {s.cognitive_load}, pažnja preostala {s.attention_remaining}")


def _line(sc: retrieval.Scored) -> str:
    m = sc.memory
    marks = []
    if sc.contested:
        marks.append("⚠ sporno")
    if m.provenance == E.Provenance.INFERRED.value:
        marks.append("izvod, ne činjenica")
    if m.scope == E.MemoryScope.DEPARTMENT.value:
        marks.append("znanje sektora")
    elif m.scope == E.MemoryScope.COMPANY.value:
        marks.append("znanje firme")
    head = f"[{m.memory_type} · pouzdanost {m.confidence}" + (
        f" · {'; '.join(marks)}" if marks else "") + "]"
    body = f"{m.title}: {m.content}" if m.title else m.content
    return f"- {head} {body}"


#: Repovi napomene koji su provenijencija, ne opis — dupliraju „izvor" i samo
#: troše tokene u paketu (ADR-0112). Seku se pre nego što napomena uđe u red;
#: hvata i kad napomena POČINJE provenijencijom (npr. „Destilovano iz …").
_PROVENIJENCIJA = ("|", "Uvezeno iz", "Destilovano iz", "(ko ", "(fajl")


def _gloss(napomene: str, limit: int) -> str:
    """Opis veštine bez repa provenijencije, skraćen na reč do `limit` znakova."""
    g = str(napomene or "")
    for mark in _PROVENIJENCIJA:
        i = g.find(mark)
        if i != -1:
            g = g[:i]
    g = g.strip(" .—-")
    if len(g) <= limit:
        return g
    return g[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-") + "…"


def _vestina_line(fact: KnowledgeFact) -> str:
    """Puna veština: koraci + kratak opis. Izvor stoji uz nju — znanje bez
    porekla se ne šalje (ADR-0084). Provenijencija iz napomene se seče, jer
    duplira izvor i jede budžet (ADR-0112); opis se skraćuje na 200 znakova."""
    koraci = fact.object_json.get("koraci") or []
    telo = "; ".join(str(k) for k in koraci)
    gloss = _gloss(fact.object_json.get("napomene") or "", 200)
    if gloss:
        telo = f"{telo} — {gloss}" if telo else gloss
    return f"- [veština · izvor {fact.source.title}] {fact.subject}: {telo}"


def _vestina_index_line(fact: KnowledgeFact) -> str:
    """Indeksna veština: ime + čemu služi, bez koraka (ADR-0112). I ona nosi
    izvor (ADR-0084). Korake agent traži kad baš ta veština zatreba."""
    gloss = _gloss(fact.object_json.get("napomene") or "", 80)
    rep = f"{fact.subject} — {gloss}" if gloss else fact.subject
    return f"- [veština · izvor {fact.source.title}] {rep}"


def _slozi_vestine(puni: list[str], indeks: list[str]) -> str:
    """Dva sloja u jednom odeljku: šta agent ima u celini, šta zna po imenu."""
    delovi: list[str] = []
    if puni:
        delovi.append("U celini (sa koracima):")
        delovi.extend(puni)
    if indeks:
        if puni:
            delovi.append("")
        delovi.append("Još veština koje imaš (ime i čemu služe; "
                      "detaljne korake traži kad zatrebaju):")
        delovi.extend(indeks)
    return "\n".join(delovi)


@functools.lru_cache(maxsize=1)
def _dosije_firme() -> str:
    """Dosije firme — ono što svaki agent zna o tome gde radi. ADR-0107.

    Stoji u repozitorijumu (`firma/dosije.md`), ne u bazi: piše ga čovek,
    menja se kroz izmenu koja prolazi kapije, i vidi se u istoriji ko ga je i
    kada promenio. Keš je trajan za život procesa — izmena stiže sa novom
    slikom, kao i kod ostalog koda.

    Ako fajla nema, odeljak je prazan i ništa se ne lomi: agent tada radi bez
    znanja o firmi, kao pre ADR-0107, a ne pada.
    """
    put = pathlib.Path(settings.BASE_DIR) / "firma" / "dosije.md"
    try:
        return put.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _sektor_persone(persona) -> str:
    """`Department.code` sektora u kome persona radi, preko otvorenog
    primarnog rasporeda (ADR-0017). Prazno kad persona nema raspored —
    tada sektor ništa ne odlučuje i ostaje poklapanje sa zadatkom i azbuka.
    """
    raspored = (
        Assignment.objects
        .filter(persona=persona, ended_at__isnull=True, is_primary=True)
        .select_related("position__department")
        .first()
    )
    return raspored.position.department.code if raspored else ""


def _vestina_kljuc(fact: KnowledgeFact, upit: set[str], sektor: str) -> tuple:
    """Redosled veština za paket (ADR-0101): prvo sektor persone, pa izvori
    bez sektora („za sve"), pa poklapanje sa tekstom zadatka, pa azbuka.

    Poklapanje je grubo i leksičko (`embeddings.stems`) i namerno je TREĆE
    po redu: korpus je engleski, zadatak je obično srpski, pa poklapanje
    često bude nula. Kad je nula, odlučuje sektor — ne azbuka, kao do sada.
    """
    izvor_sektor = fact.source.sector
    svoj = 1 if izvor_sektor and izvor_sektor == sektor else 0
    za_sve = 1 if not izvor_sektor else 0
    pogodak = 0
    if upit:
        napomene = str(fact.object_json.get("napomene") or "")
        pogodak = (3 * len(upit & embeddings.stems(fact.subject))
                   + len(upit & embeddings.stems(napomene)))
    return (-svoj, -za_sve, -pogodak, fact.subject)


def _semanticki_rang(query: str, base: list):
    """Veštine po kosinusnoj sličnosti sa zadatkom (ADR-0120).

    Vraća None ako model nije dostupan (fastembed/offline) ili ako nijedna
    veština još nema embedding — tada se pada na leksičko (ADR-0101), pa sistem
    radi i bez modela (ADR-0009). Veštine bez vektora se dodaju na kraj, da
    nova (još neembedovana) veština ne ispadne iz paketa.
    """
    from pgvector.django import CosineDistance

    from apps.memory.models import KnowledgeEmbedding
    try:
        qv = embeddings.embed_semanticki(query)
    except Exception as e:  # noqa: BLE001 — model nedostupan: leksički fallback
        log.warning("semantički rang veština pao, leksički fallback: %s", e)
        return None
    by_id = {f.id: f for f in base}
    mk = embeddings.vestina_model_key()
    poredak = list(
        KnowledgeEmbedding.objects
        .filter(model_key=mk, fact_id__in=list(by_id))
        .annotate(dist=CosineDistance("embedding", qv))
        .order_by("dist").values_list("fact_id", flat=True))
    facts = [by_id[fid] for fid in poredak if fid in by_id]
    if not facts:
        return None
    vidjeni = set(poredak)
    facts += [f for fid, f in by_id.items() if fid not in vidjeni]
    return facts


def _rangiraj_vestine(persona, query: str, sektor: str) -> list:
    """Redosled veština za paket: semantički (ADR-0120) kad ima upita i modela,
    inače leksički po sektoru (ADR-0101)."""
    base = list(
        KnowledgeFact.objects
        .filter(predicate=VESTINA_PREDIKAT, source__is_active=True,
                source__license_box=E.LicenseBox.SLOBODNA.value)
        .select_related("source"))
    if query.strip():
        sem = _semanticki_rang(query, base)
        if sem is not None:
            return sem
    upit = embeddings.stems(query) if query.strip() else set()
    return sorted(base, key=lambda f: _vestina_kljuc(f, upit, sektor))



def build(persona, run, profile: E.RetrievalProfile, *, query: str = "",
          max_tokens: int | None = None, now: datetime | None = None,
          memory_types: list[E.MemoryType] | None = None) -> Pack:
    now = now or timezone.now()
    budget = max_tokens or (E.PROFILE_MEMORY_TOKENS[profile] + CORE_OVERHEAD_TOKENS)
    sections = {
        "persona_core": _core(persona),
        # ADR-0107 — gde agent radi. Ide odmah iza toga ko je on, a pre svega
        # ostalog: bez toga agent izmišlja kupce, cene i usluge kojih nema.
        "firma": _dosije_firme(),
        "current_state": _state(persona),
        "task_goal": query,
        "policy_constraints": "\n".join(POLICY_LINES),
    }
    def render(secs: dict[str, str]) -> str:
        return "\n\n".join(f"## {k}\n{v}" for k, v in secs.items() if v)

    # Zaglavlje sekcije „retrieved_memory" košta i kad je prazna — zato +8.
    fixed = tokens(render(sections)) + 8
    if fixed > budget:  # predugačak upit ne sme da probije plafon
        keep = max(0, len(query) - (fixed - budget) * 4)
        sections["task_goal"] = query[:keep]
        fixed = tokens(render(sections)) + 8
    room = max(0, min(E.PROFILE_MEMORY_TOKENS[profile], budget - fixed))

    candidates = retrieval.retrieve(persona, query, profile, now=now, memory_types=memory_types)
    chosen: list[retrieval.Scored] = []
    lines: list[str] = []
    used = 0
    truncated = False
    for sc in candidates:
        line = _line(sc)
        t = tokens(line + "\n")
        if used + t > room:
            truncated = True
            continue
        chosen.append(sc)
        lines.append(line)
        used += t

    # ADR-0096 — veštine su kućno znanje; dobijaju SVOJ plafon POVRH onog za
    # memoriju (zato se `budget`/`room` iznad ne diraju), i ne smeju da ga
    # oduzmu memoriji. Ulaze samo činjenice čiji je izvor aktivan i čija je
    # kutija licence tačno `SLOBODNA` — ZARAZNA, ZABRANJENA i NEPOZNATA ne
    # ulaze nikad, ni uz napomenu (ADR-0059). Provera ide ovde, pri
    # sastavljanju paketa, ne pri uvozu (ADR-0095).
    #
    # ADR-0101 menja ono što je ADR-0096 tačka 5 ostavila otvoreno: izbor
    # više nije azbučni. Redosled je sektor persone → izvori bez sektora →
    # poklapanje sa zadatkom → azbuka. Razlog je izmeren 16.10.2026: sa 452
    # veštine u bazi, u paket je ulazilo 9 i to uvek istih devet, a 443 nisu
    # stizale ni do koga. Rangiranje se radi u Pythonu, nad svim podobnim
    # redovima — merenje kaže da ih je reda nekoliko stotina, pa to prolazi;
    # kad korpus naraste, ovo je prvo mesto koje treba ponovo izmeriti.
    vestina_budget = E.PROFILE_VESTINE_TOKENS[profile]
    sektor = _sektor_persone(persona)
    vestina_candidates = _rangiraj_vestine(persona, query, sektor)
    # ADR-0112 — vrh rangiranja ulazi U CELINI (koraci); ostalo kao indeks
    # (ime + čemu služi), dok traje budžet. Tako agent zna ceo svoj alat
    # (~30-40 veština), a detaljne korake ima za ono najverovatnije potrebno.
    # Izmereno 18.10.2026: pune linije su ~246 tokena, pa je u 1000 stajalo
    # samo 4 od 451 veštine; indeksna linija je ~23 tokena.
    puni_lines: list[str] = []
    indeks_lines: list[str] = []
    vestina_ids: list[str] = []
    used_v = 0
    for fact in vestina_candidates:
        pun = len(puni_lines) < VESTINE_PUNIH
        line = _vestina_line(fact) if pun else _vestina_index_line(fact)
        t = tokens(line + "\n")
        if used_v + t > vestina_budget and pun:
            # Puna ne staje — probaj makar ime u indeks, da veština ne ispadne.
            line = _vestina_index_line(fact)
            t = tokens(line + "\n")
            pun = False
        if used_v + t > vestina_budget:
            truncated = True
            continue
        (puni_lines if pun else indeks_lines).append(line)
        vestina_ids.append(str(fact.id))
        used_v += t

    sections["vestine"] = _slozi_vestine(puni_lines, indeks_lines)
    sections["retrieved_memory"] = "\n".join(lines)
    text = render(sections)
    total = tokens(text)

    with transaction.atomic():
        record = MemoryContextPack.objects.create(
            persona=persona, run=run, purpose=E.PROFILE_PURPOSE[profile].value,
            query_text=query, memory_ids=[str(s.memory.id) for s in chosen],
            vestina_ids=vestina_ids,
            scores={str(s.memory.id): {"R": s.score, **s.breakdown} for s in chosen},
            token_count=total, truncated=truncated,
            pack_hash=hashlib.sha256(text.encode()).hexdigest(), built_at=now,
        )
        MemoryItem.objects.filter(id__in=[s.memory.id for s in chosen]).update(
            recall_count=F("recall_count") + 1, last_recalled_at=now)
        bus.emit("context.built",
                 {"profile": profile.value, "item_count": len(chosen), "token_estimate": total},
                 persona_id=persona.public_id, run_id=run.public_id)
    return Pack(record, text, sections, chosen)
