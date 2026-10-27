"""LLM ekstraktor tvrdnji (ADR-0031 sloj 4a, opcija B).

Isti potpis kao deterministička osnova `tvrdnje.izvuci(blocks) -> list[dict]`,
ali kandidate daje model kroz F7 gateway. LLM je POJAČAVAČ nad osnovom, ne
zamena (Canon §21 — prvo osnova + merenje, pa pravi alat).

**Dve tvrde granice koje čuva KOD, ne poverenje u model:**

1. Spoljni model se zove SAMO kroz gateway i samo kad F7 dozvoli (ADR-0009):
   `LLM_EXTERNAL_ENABLED=true`, ruta `data_training_allowed=True` (provajder NE
   uči na našim podacima) i postoji ključ. Lanac za ovu svrhu NEMA lokalni
   šablon (kao `transcribe`, ADR-0078 §4): šablon ne ume da izvlači, pa bi
   izmislio tvrdnju. Kad spoljne rute nema ili padne → DETERMINISTIČKA osnova.

2. Filter uzemljenja (`_uzemlji`): tvrdnja mora da citira postojeći `block_id`
   I da joj subjekat i vrednost budu UZEMLJENI u tom bloku — preklapanje reči
   fraze sa rečima bloka ≥ `_PRAG`. Reč koje nema u bloku obara preklapanje, pa
   halucinacija (izmišljen block_id ili reči kojih nema) nikad ne uđe kao
   činjenica (Canon §10.4: OBSERVED, ne INFERRED). Prag je podesiv: strože =
   veća preciznost, niži odziv. Prompt traži DOSLOVNE isečke, pa preklapanje
   toleriše samo preraspored / izostavljene pomoćne reči, ne parafrazu.
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

_MAX_BLOKOVA = 40  # koliko paragrafa stane u jedan prompt (kratko, merljivo)
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


def _pozovi(gateway, rute: list, prompt: str, persona=None) -> str | None:
    """Tekst prvog uspelog modela iz lanca; None ako nijedna ruta ne prođe."""
    for ruta in rute:
        try:
            g = gateway.generate(E.LLMPurpose.EXTRACT, _SISTEM, prompt,
                                  persona=persona, only=ruta)
            return g.text
        except gateway.LLMError:
            continue
    return None


def _llm_izvuci(blocks: list[Any], persona=None) -> tuple[list[dict] | None, list[dict]]:
    """(sirovi_kandidati, uzemljeni) po svim delovima; (None, []) ako model nije zvan.

    `sirovi` = sve što model vrati (pre uzemljenja), radi dijagnostike.
    (None, []) kad spoljne rute nema ili model padne — poziv za fallback na osnovu.
    """
    from apps.llm_gateway import gateway

    rute = _spoljne_rute(persona)
    if not rute:
        return None, []
    paragrafi = [b for b in blocks if getattr(b, "block_type", "") == "paragraph"]
    if not paragrafi:
        return None, []
    sirovi: list[dict] = []
    uzemljeni: list[dict] = []
    for poc in range(0, len(paragrafi), _MAX_BLOKOVA):
        deo = paragrafi[poc:poc + _MAX_BLOKOVA]
        tekst = _pozovi(gateway, rute, _prompt(deo), persona)
        if tekst is None:
            return None, []  # model nedostupan → cela osnova (ne mešamo slojeve)
        kand = _parse(tekst)
        sirovi.extend(kand)
        uzemljeni.extend(_uzemlji(kand, deo))
    return sirovi, uzemljeni


def izvuci(blocks: Iterable[Any], *, persona=None) -> list[dict]:
    """LLM kandidat-tvrdnje (uzemljene); fallback na determinističku osnovu.

    Isti potpis kao `tvrdnje.izvuci`. Kad spoljni model nije dostupan (isključen,
    bez ključa, pad, ili prazan/neuzemljen odgovor), vraća `tvrdnje.izvuci`.
    """
    blocks = list(blocks)
    osnova = tvrdnje.izvuci(blocks)
    try:
        sirovi, uzemljeni = _llm_izvuci(blocks, persona)
    except Exception:  # bilo kakav propust LLM puta → deterministička osnova
        log.warning("LLM ekstrakt pao, fallback na osnovu", exc_info=True)
        return osnova
    if sirovi is None:
        return osnova
    return uzemljeni if uzemljeni else osnova


def meri(blocks: Iterable[Any], *, persona=None) -> dict:
    """Dijagnostika: koliko model vrati (sirovo) vs koliko prođe uzemljenje."""
    blocks = list(blocks)
    try:
        sirovi, uzemljeni = _llm_izvuci(blocks, persona)
    except Exception:
        log.warning("LLM ekstrakt (meri) pao", exc_info=True)
        return {"model_zvan": False, "sirovo": 0, "uzemljeno": 0}
    if sirovi is None:
        return {"model_zvan": False, "sirovo": 0, "uzemljeno": 0}
    return {"model_zvan": True, "sirovo": len(sirovi), "uzemljeno": len(uzemljeni)}


def upisi(document, *, persona=None) -> dict[str, int]:
    """Izvuci (LLM ili osnova) i upiši tvrdnje — isti pisač kao `tvrdnje.upisi`."""
    kandidati = izvuci(document.blocks.all(), persona=persona)
    return tvrdnje.upisi(document, kandidati=kandidati)
