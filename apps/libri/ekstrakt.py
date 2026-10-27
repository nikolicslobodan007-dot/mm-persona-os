"""LLM ekstraktor tvrdnji (ADR-0031 sloj 4a, opcija B).

Isti potpis kao deterministička osnova `tvrdnje.izvuci(blocks) -> list[dict]`,
ali kandidate daje model kroz F7 gateway. LLM je POJAČAVAČ nad osnovom, ne
zamena (Canon §21 — prvo osnova + merenje, pa pravi alat).

**Dve tvrde granice koje čuva KOD, ne poverenje u model:**

1. Spoljni model se zove SAMO kroz gateway i samo kad F7 dozvoli (ADR-0009):
   `LLM_EXTERNAL_ENABLED=true`, ruta `data_training_allowed=True` (provajder NE
   uči na našim podacima) i postoji ključ. Lanac za ovu svrhu NEMA lokalni
   šablon (kao `transcribe`, ADR-0078 §4): šablon ne ume da izvlači, pa bi
   izmislio tvrdnju. Kad spoljne rute nema → DETERMINISTIČKA osnova.

2. Filter uzemljenja (`_uzemlji`): tvrdnja mora da citira postojeći `block_id`
   I da joj subjekat i vrednost budu UZEMLJENI u tom bloku — preklapanje reči
   fraze sa rečima bloka ≥ `_PRAG`. Reč koje nema u bloku obara preklapanje, pa
   halucinacija nikad ne uđe kao činjenica (Canon §10.4: OBSERVED, ne INFERRED).

Dokument se deli na delove (`_MAX_BLOKOVA`) zbog veličine prompta/izlaza. **Pali
deo se PRESKAČE, ne ruši ceo dokument** — uspeli delovi se zadrže. Dijagnostika
(`meri`) vraća po delu: koliko vraćeno, koliko uzemljeno, razlog završetka.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from typing import Any

from apps.libri import tvrdnje
from common import enums as E

log = logging.getLogger(__name__)

PREDIKAT = tvrdnje.PREDIKAT

_MAX_BLOKOVA = 15  # paragrafa po pozivu (manje = manji ulaz/izlaz, manje praznih/timeouta)
_PRAG = 0.8        # minimalno preklapanje reči fraze sa blokom (0..1)

_SISTEM = (
    "Ti si ekstraktor činjenica iz srpskog teksta. Iz datih blokova izvuci SVE "
    "tvrdnje navedene u tekstu (i definicije i opise radnji). Ne zaključuj, ne "
    "uopštavaj, ne dodaj ništa čega nema u bloku. Subjekat i vrednost MORAJU biti "
    "DOSLOVNI isečci reči iz tog istog bloka — prepiši reči kako stoje, bez "
    "prepričavanja i bez menjanja oblika reči. Uz svaku tvrdnju navedi block_id iz "
    "kog je uzeta. Vrati isključivo JSON listu objekata sa ključevima subject, "
    "relacija, vrednost, block_id. Bez objašnjenja."
)

_TOK = re.compile(r"[0-9a-zčćžšđ]+")
#: Česte pomoćne reči (≥3 znaka) — ne računaju se u preklapanje (kraće već ispadaju).
_STOP_TOK = frozenset((
    "koji", "koja", "koje", "kao", "ili", "što", "jer", "ali", "pa", "te", "sa",
))


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _tokeni(s: str) -> list[str]:
    return [t for t in _TOK.findall(_norm(s)) if len(t) >= 3 and t not in _STOP_TOK]


def _preklapanje(fraza: str, blok_tokeni: set[str]) -> float:
    toks = _tokeni(fraza)
    if not toks:
        return 0.0
    return sum(1 for t in toks if t in blok_tokeni) / len(toks)


def _prompt(blocks: list[Any]) -> str:
    redovi = [f"[{b.block_id}] {' '.join((b.text or '').split())}" for b in blocks]
    return "Blokovi:\n" + "\n".join(redovi)


def _parse(text: str) -> list[dict]:
    """JSON lista iz odgovora modela; toleriše ```json`` omot i tekst okolo."""
    t = (text or "").strip()
    poc, kraj = t.find("["), t.rfind("]")
    if poc == -1 or kraj == -1 or kraj < poc:
        return []
    try:
        data = json.loads(t[poc:kraj + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for r in data:
        if not isinstance(r, dict):
            continue
        out.append({
            "subject": str(r.get("subject", "")).strip(),
            "relacija": str(r.get("relacija", "")).strip(),
            "vrednost": str(r.get("vrednost", "")).strip(),
            "block_id": str(r.get("block_id", "")).strip(),
        })
    return out


def _uzemlji(kandidati: list[dict], blocks: Iterable[Any]) -> list[dict]:
    """Zadrži samo tvrdnje UZEMLJENE u citiranom bloku (preklapanje ≥ _PRAG)."""
    po_bloku = {b.block_id: (set(_tokeni(b.text)), b) for b in blocks}
    out: list[dict] = []
    vidjeno: set = set()
    for k in kandidati:
        par = po_bloku.get(k["block_id"])
        if par is None:
            continue  # izmišljen/nepostojeći block_id → baca se
        blok_tokeni, b = par
        subj, vred = k["subject"], k["vrednost"]
        if not subj or not vred or len(subj) > 220 or not (3 <= len(vred) <= 300):
            continue
        if (_preklapanje(subj, blok_tokeni) < _PRAG
                or _preklapanje(vred, blok_tokeni) < _PRAG):
            continue  # reči kojih nema u bloku → baca se (anti-halucinacija)
        kljuc = (_norm(subj), _norm(vred), k["block_id"])
        if kljuc in vidjeno:
            continue
        vidjeno.add(kljuc)
        out.append({
            "subject": subj[:220], "relacija": k["relacija"][:120], "vrednost": vred,
            "block_id": k["block_id"], "source_page": b.source_page, "confidence": 0.7,
        })
    return out


def _iz_teksta(text: str, blocks: Iterable[Any]) -> list[dict]:
    """Odgovor modela → uzemljene tvrdnje (čista funkcija, bez mreže i baze)."""
    return _uzemlji(_parse(text), list(blocks))


def _spoljne_rute(persona=None) -> list:
    """Uključene SPOLJNE rute za svrhu EXTRACT, bez lokalnog šablona (presedan transcribe)."""
    from apps.llm_gateway.gateway import LOCAL_PROVIDER
    from apps.llm_gateway.models import AgentRoute, LLMRoute

    moje = []
    if persona is not None:
        moje = [ar.route for ar in AgentRoute.objects.filter(
            persona=persona, purpose=E.LLMPurpose.EXTRACT.value, is_enabled=True,
        ).select_related("route").order_by("priority")]
    uzeti = {r.pk for r in moje}
    firmine = [r for r in LLMRoute.objects.filter(
        purpose=E.LLMPurpose.EXTRACT.value, is_enabled=True).exclude(
        provider=LOCAL_PROVIDER).order_by("priority", "name") if r.pk not in uzeti]
    return moje + firmine


def _pozovi(gateway, rute: list, prompt: str, persona=None) -> tuple[str | None, str]:
    """(tekst, razlog). tekst=None ako nijedna ruta ne prođe; razlog za dijagnostiku."""
    razlog = "no_route"
    for ruta in rute:
        try:
            g = gateway.generate(E.LLMPurpose.EXTRACT, _SISTEM, prompt,
                                  persona=persona, only=ruta)
            return g.text, (g.record.finish_reason or "ok")
        except gateway.LLMError as e:
            razlog = (e.detail or e.code or "greška")[:60]
            continue
    return None, razlog


def _llm_izvuci(blocks: list[Any], persona=None) -> tuple[bool, list[dict], list[dict], list[dict]]:
    """(primenjiv, sirovi, uzemljeni, delovi).

    primenjiv=False → nema rute ili nema paragrafa → fallback na osnovu.
    Pali deo se PRESKAČE (ne ruši ceo dokument); uspeli delovi se zadrže.
    `delovi`: po jedan {sirovo, uzemljeno, razlog} radi dijagnostike.
    """
    from apps.llm_gateway import gateway

    rute = _spoljne_rute(persona)
    if not rute:
        return False, [], [], []
    paragrafi = [b for b in blocks if getattr(b, "block_type", "") == "paragraph"]
    if not paragrafi:
        return False, [], [], []
    sirovi: list[dict] = []
    uzemljeni: list[dict] = []
    delovi: list[dict] = []
    for poc in range(0, len(paragrafi), _MAX_BLOKOVA):
        deo = paragrafi[poc:poc + _MAX_BLOKOVA]
        tekst, razlog = _pozovi(gateway, rute, _prompt(deo), persona)
        if tekst is None:
            delovi.append({"sirovo": 0, "uzemljeno": 0, "razlog": razlog})
            continue  # pali deo se preskače, ne ruši ostale
        kand = _parse(tekst)
        uz = _uzemlji(kand, deo)
        sirovi.extend(kand)
        uzemljeni.extend(uz)
        delovi.append({"sirovo": len(kand), "uzemljeno": len(uz), "razlog": razlog})
    return True, sirovi, uzemljeni, delovi


def izvuci(blocks: Iterable[Any], *, persona=None) -> list[dict]:
    """LLM kandidat-tvrdnje (uzemljene); fallback na determinističku osnovu.

    Isti potpis kao `tvrdnje.izvuci`. Kad spoljni model nije dostupan (isključen,
    bez ključa, pad, ili prazan/neuzemljen odgovor), vraća `tvrdnje.izvuci`.
    """
    blocks = list(blocks)
    osnova = tvrdnje.izvuci(blocks)
    try:
        primenjiv, _sirovi, uzemljeni, _delovi = _llm_izvuci(blocks, persona)
    except Exception:  # bilo kakav propust LLM puta → deterministička osnova
        log.warning("LLM ekstrakt pao, fallback na osnovu", exc_info=True)
        return osnova
    if not primenjiv:
        return osnova
    return uzemljeni if uzemljeni else osnova


def meri(blocks: Iterable[Any], *, persona=None) -> dict:
    """Dijagnostika: sirovo vs uzemljeno, ukupno i po delu (razlog završetka)."""
    blocks = list(blocks)
    try:
        primenjiv, sirovi, uzemljeni, delovi = _llm_izvuci(blocks, persona)
    except Exception:
        log.warning("LLM ekstrakt (meri) pao", exc_info=True)
        return {"model_zvan": False, "sirovo": 0, "uzemljeno": 0, "delovi": []}
    return {"model_zvan": primenjiv, "sirovo": len(sirovi),
            "uzemljeno": len(uzemljeni), "delovi": delovi}


def upisi(document, *, persona=None) -> dict[str, int]:
    """Izvuci (LLM ili osnova) i upiši tvrdnje — isti pisač kao `tvrdnje.upisi`."""
    kandidati = izvuci(document.blocks.all(), persona=persona)
    return tvrdnje.upisi(document, kandidati=kandidati)
