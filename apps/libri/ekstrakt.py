"""LLM ekstraktor tvrdnji (ADR-0031 sloj 4a, opcija B).

Isti potpis kao deterministička osnova `tvrdnje.izvuci(blocks) -> list[dict]`,
ali kandidate daje model kroz F7 gateway. LLM je POJAČAVAČ nad osnovom, ne
zamena (Canon §21 — prvo osnova + merenje, pa pravi alat).

**Dve tvrde granice koje čuva KOD, ne poverenje u model:**

1. Spoljni model se zove SAMO kroz gateway i samo kad F7 dozvoli (ADR-0009):
   `LLM_EXTERNAL_ENABLED=true`, ruta `data_training_allowed=True` (provajder NE
   uči na našim podacima — prompt nosi naš tekst) i postoji ključ. Lanac za ovu
   svrhu NEMA lokalni šablon (kao `transcribe`, ADR-0078 §4): šablon ne ume da
   izvlači, pa bi izmislio tvrdnju. Kad spoljne rute nema ili padne, vraća se
   DETERMINISTIČKA osnova (`tvrdnje.izvuci`) — ništa se ne izmišlja, sistem radi
   bez ijednog ključa.

2. Filter uzemljenja (`_uzemlji`): svaka tvrdnja koju model vrati mora da citira
   postojeći `block_id` iz dokumenta I da joj subjekat i vrednost budu DOSLOVNO u
   tekstu tog bloka. Šta god ne prođe — baca se. Tako halucinacija (izmišljen
   block_id ili tekst kog nema u bloku) nikad ne uđe kao činjenica (Canon §10.4:
   tvrdnja je OBSERVED iz izvora, ne INFERRED).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from apps.libri import tvrdnje
from common import enums as E

log = logging.getLogger(__name__)

PREDIKAT = tvrdnje.PREDIKAT

_MAX_BLOKOVA = 40  # koliko paragrafa stane u jedan prompt (kratko, merljivo)

_SISTEM = (
    "Ti si ekstraktor činjenica iz srpskog teksta. Iz datih blokova izvuci samo "
    "tvrdnje koje su DOSLOVNO navedene u tekstu. Ne zaključuj, ne uopštavaj, ne "
    "dodaj ništa čega nema u bloku. Svaku tvrdnju vrati kao trojku subjekat / "
    "relacija / vrednost i obavezno navedi block_id iz kog je uzeta; subjekat i "
    "vrednost moraju biti reči iz tog bloka. Vrati isključivo JSON listu objekata "
    "sa ključevima subject, relacija, vrednost, block_id. Bez objašnjenja."
)


def _prompt(blocks: list[Any]) -> str:
    redovi = [f"[{b.block_id}] {' '.join((b.text or '').split())}" for b in blocks]
    return "Blokovi:\n" + "\n".join(redovi)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


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
    """Zadrži samo tvrdnje DOSLOVNO uzemljene u citiranom bloku (Canon §10.4)."""
    po_bloku = {b.block_id: (_norm(b.text), b) for b in blocks}
    out: list[dict] = []
    vidjeno: set = set()
    for k in kandidati:
        par = po_bloku.get(k["block_id"])
        if par is None:
            continue  # izmišljen/nepostojeći block_id → baca se
        tekst_norm, b = par
        subj, vred = k["subject"], k["vrednost"]
        if not subj or not vred or len(subj) > 220 or not (3 <= len(vred) <= 300):
            continue
        if _norm(subj) not in tekst_norm or _norm(vred) not in tekst_norm:
            continue  # nije doslovno u bloku → baca se
        kljuc = (subj, vred, k["block_id"])
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


def izvuci(blocks: Iterable[Any], *, persona=None) -> list[dict]:
    """LLM kandidat-tvrdnje (uzemljene); fallback na determinističku osnovu.

    Isti potpis kao `tvrdnje.izvuci`. Kad spoljni model nije dostupan (isključen,
    bez ključa, pad, ili prazan/neuzemljen odgovor), vraća `tvrdnje.izvuci`.
    """
    blocks = list(blocks)
    osnova = tvrdnje.izvuci(blocks)
    try:
        from apps.llm_gateway import gateway

        rute = _spoljne_rute(persona)
        if not rute:
            return osnova
        paragrafi = [b for b in blocks if getattr(b, "block_type", "") == "paragraph"]
        if not paragrafi:
            return osnova
        sve: list[dict] = []
        for poc in range(0, len(paragrafi), _MAX_BLOKOVA):
            deo = paragrafi[poc:poc + _MAX_BLOKOVA]
            tekst = _pozovi(gateway, rute, _prompt(deo), persona)
            if tekst is None:
                return osnova  # model nedostupan → cela osnova (ne mešamo slojeve)
            sve.extend(_iz_teksta(tekst, deo))
        return sve if sve else osnova
    except Exception:  # bilo kakav propust LLM puta → deterministička osnova
        log.warning("LLM ekstrakt pao, fallback na osnovu", exc_info=True)
        return osnova


def upisi(document, *, persona=None) -> dict[str, int]:
    """Izvuci (LLM ili osnova) i upiši tvrdnje — isti pisač kao `tvrdnje.upisi`."""
    kandidati = izvuci(document.blocks.all(), persona=persona)
    return tvrdnje.upisi(document, kandidati=kandidati)
