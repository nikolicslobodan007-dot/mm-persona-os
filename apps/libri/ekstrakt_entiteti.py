"""LLM ekstraktor entiteta i odnosa (ADR-0031 sloj 4b, pojačavač nad osnovom).

Isti potpis kao deterministička osnova `entiteti.izvuci_*(blocks)`, ali kandidate
daje model kroz F7 gateway. LLM je POJAČAVAČ, ne zamena (Canon §21 — prvo osnova
+ merenje, pa pravi alat). Osnova ostaje donja granica: kad modela nema ili ne
vrati ništa uzemljeno, vraćamo DETERMINISTIČKU osnovu (`entiteti.izvuci_*`).

**Dve tvrde granice koje čuva KOD, ne poverenje u model** (isti obrazac kao
`ekstrakt` za tvrdnje):

1. Spoljni model se zove SAMO kroz gateway i samo kad F7 dozvoli (ADR-0009):
   `LLM_EXTERNAL_ENABLED=true`, ruta `data_training_allowed=True` (provajder NE
   uči na našim podacima) i postoji ključ. Svrha EXTRACT nema lokalni šablon
   (presedan `transcribe`): šablon ne ume da izvlači, pa bi izmislio entitet.
   Kad spoljne rute nema → DETERMINISTIČKA osnova.

2. Filter uzemljenja: entitet mora da citira postojeći `block_id` i da mu naziv
   bude UZEMLJEN u tom bloku (preklapanje reči ≥ `_PRAG`); vrsta mora biti iz
   `entiteti.VRSTE`. Odnos opstaje samo IZMEĐU DVA već uzemljena entiteta, sa
   tipom iz `entiteti.TIPOVI_ODNOSA`, i to u bloku u kom se oba naziva uzemljuju
   (zato halucinovana veza ne uđe kao činjenica — Canon §10.4: OBSERVED).

Datum događaja (`desilo_se`) se NE uzima od modela nego se čita iz samog bloka
(`entiteti._datum`) — dvostruko vreme (ADR-0031 §3.2) ostaje poreklom iz izvora.
Dokument se deli na delove (`_MAX_BLOKOVA`); pali deo se PRESKAČE, ne ruši ceo
dokument. Grani preklapanja i rute dele se sa `ekstrakt` (jedan izvor istine).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from apps.libri import ekstrakt, entiteti
from common import enums as E

log = logging.getLogger(__name__)

VRSTE = entiteti.VRSTE
TIPOVI_ODNOSA = entiteti.TIPOVI_ODNOSA

_SISTEM = (
    "Ti si ekstraktor entiteta i odnosa iz srpskog teksta. Iz datih blokova izvuci "
    "imenovane entitete i veze između njih. Ne zaključuj, ne uopštavaj, ne dodaj "
    "ništa čega nema u bloku. Naziv entiteta MORA biti DOSLOVAN isečak reči iz tog "
    "istog bloka — prepiši reči kako stoje. Vrsta entiteta je jedna od: "
    "osoba, organizacija, dogadjaj. Odnos postoji samo IZMEĐU DVA izvučena entiteta; "
    "tip odnosa je jedan od: radi_u, vodi, deo_od, nalazi_se_u, osnovao. Uz svaki "
    "entitet i odnos navedi block_id iz kog je uzet. Vrati ISKLJUČIVO JSON objekat "
    'oblika {"entiteti":[{"naziv":"...","vrsta":"...","block_id":"..."}],'
    '"odnosi":[{"subjekat":"...","objekat":"...","tip":"...","block_id":"..."}]}. '
    "Bez objašnjenja."
)


def _prompt(blocks: list[Any]) -> str:
    redovi = [f"[{b.block_id}] {' '.join((b.text or '').split())}" for b in blocks]
    return "Blokovi:\n" + "\n".join(redovi)


def _parse(text: str) -> tuple[list[dict], list[dict]]:
    """JSON objekat iz odgovora modela; toleriše ```json`` omot i tekst okolo."""
    t = (text or "").strip()
    poc, kraj = t.find("{"), t.rfind("}")
    if poc == -1 or kraj == -1 or kraj < poc:
        return [], []
    try:
        data = json.loads(t[poc:kraj + 1])
    except (ValueError, TypeError):
        return [], []
    if not isinstance(data, dict):
        return [], []
    ent = []
    for r in data.get("entiteti", []) or []:
        if not isinstance(r, dict):
            continue
        ent.append({
            "naziv": str(r.get("naziv", "")).strip(),
            "vrsta": str(r.get("vrsta", "")).strip().lower(),
            "block_id": str(r.get("block_id", "")).strip(),
        })
    odn = []
    for r in data.get("odnosi", []) or []:
        if not isinstance(r, dict):
            continue
        odn.append({
            "subjekat": str(r.get("subjekat", "")).strip(),
            "objekat": str(r.get("objekat", "")).strip(),
            "tip": str(r.get("tip", "")).strip().lower(),
            "block_id": str(r.get("block_id", "")).strip(),
        })
    return ent, odn


def _uzemlji_entitete(kandidati: list[dict], blocks: Iterable[Any]) -> list[dict]:
    """Zadrži entitete UZEMLJENE u citiranom bloku (preklapanje ≥ ekstrakt._PRAG, vrsta OK)."""
    po_bloku = {b.block_id: (set(ekstrakt._tokeni(b.text)), b) for b in blocks}
    out: list[dict] = []
    vidjeno: set = set()
    for k in kandidati:
        par = po_bloku.get(k["block_id"])
        if par is None:
            continue  # izmišljen/nepostojeći block_id → baca se
        blok_tokeni, b = par
        naziv, vrsta = k["naziv"], k["vrsta"]
        if vrsta not in VRSTE:
            continue  # vrsta van vokabulara → baca se
        if not naziv or not (2 <= len(naziv) <= 220):
            continue
        if ekstrakt._preklapanje(naziv, blok_tokeni) < ekstrakt._PRAG:
            continue  # reči kojih nema u bloku → baca se (anti-halucinacija)
        kljuc = (vrsta, ekstrakt._norm(naziv))
        if kljuc in vidjeno:
            continue
        vidjeno.add(kljuc)
        datum = entiteti._datum(b.text or "") if vrsta == "dogadjaj" else None
        out.append({
            "name": naziv[:220], "kind": vrsta, "normalized": ekstrakt._norm(naziv)[:220],
            "block_id": k["block_id"], "source_page": b.source_page,
            "desilo_se": datum.isoformat() if datum else None, "objavljeno": None,
            "confidence": 0.7,
        })
    return out


def _uzemlji_odnose(kandidati: list[dict], uzemljeni_e: list[dict],
                    blocks: Iterable[Any]) -> list[dict]:
    """Odnos samo IZMEĐU dva uzemljena entiteta, oba uzemljena u citiranom bloku."""
    po_bloku = {b.block_id: (set(ekstrakt._tokeni(b.text)), b) for b in blocks}
    imena = {e["normalized"] for e in uzemljeni_e}
    out: list[dict] = []
    vidjeno: set = set()
    for k in kandidati:
        par = po_bloku.get(k["block_id"])
        if par is None:
            continue
        blok_tokeni, b = par
        subj, obj, tip = k["subjekat"], k["objekat"], k["tip"]
        if tip not in TIPOVI_ODNOSA:
            continue  # tip van vokabulara → baca se
        ns, no = ekstrakt._norm(subj), ekstrakt._norm(obj)
        if ns not in imena or no not in imena:
            continue  # veza van prepoznatih entiteta → baca se (visoka preciznost)
        if (ekstrakt._preklapanje(subj, blok_tokeni) < ekstrakt._PRAG
                or ekstrakt._preklapanje(obj, blok_tokeni) < ekstrakt._PRAG):
            continue  # oba naziva moraju biti u citiranom bloku → baca halucinaciju
        kljuc = (ns, tip, no)
        if kljuc in vidjeno:
            continue
        vidjeno.add(kljuc)
        out.append({
            "subject": subj[:220], "object": obj[:220], "relation_type": tip,
            "block_id": k["block_id"], "source_page": b.source_page, "confidence": 0.7,
        })
    return out


def _iz_teksta(text: str, blocks: Iterable[Any]) -> tuple[list[dict], list[dict]]:
    """Odgovor modela → (uzemljeni entiteti, uzemljeni odnosi). Bez mreže i baze."""
    blocks = list(blocks)
    kand_e, kand_o = _parse(text)
    uz_e = _uzemlji_entitete(kand_e, blocks)
    uz_o = _uzemlji_odnose(kand_o, uz_e, blocks)
    return uz_e, uz_o


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


def _llm_izvuci(blocks: list[Any], persona=None):
    """(primenjiv, sirovo_e, uzemljeni_e, sirovo_o, uzemljeni_o, delovi).

    primenjiv=False → nema rute ili nema paragrafa → fallback na osnovu.
    Pali deo se PRESKAČE (ne ruši ceo dokument); uspeli delovi se zadrže.
    Odnosi se uzemljuju nad entitetima ISTOG dela (lokalno, visoka preciznost).
    """
    from apps.llm_gateway import gateway

    rute = ekstrakt._spoljne_rute(persona)
    if not rute:
        return False, 0, [], 0, [], []
    paragrafi = [b for b in blocks if getattr(b, "block_type", "") == "paragraph"]
    if not paragrafi:
        return False, 0, [], 0, [], []
    sirovo_e = sirovo_o = 0
    uzemljeni_e: list[dict] = []
    uzemljeni_o: list[dict] = []
    delovi: list[dict] = []
    for poc in range(0, len(paragrafi), ekstrakt._MAX_BLOKOVA):
        deo = paragrafi[poc:poc + ekstrakt._MAX_BLOKOVA]
        tekst, razlog = _pozovi(gateway, rute, _prompt(deo), persona)
        if tekst is None:
            delovi.append({"entiteti_sirovo": 0, "entiteti_uzemljeno": 0,
                           "odnosi_sirovo": 0, "odnosi_uzemljeno": 0, "razlog": razlog})
            continue  # pali deo se preskače, ne ruši ostale
        kand_e, kand_o = _parse(tekst)
        uz_e = _uzemlji_entitete(kand_e, deo)
        uz_o = _uzemlji_odnose(kand_o, uz_e, deo)
        sirovo_e += len(kand_e)
        sirovo_o += len(kand_o)
        uzemljeni_e.extend(uz_e)
        uzemljeni_o.extend(uz_o)
        delovi.append({"entiteti_sirovo": len(kand_e), "entiteti_uzemljeno": len(uz_e),
                       "odnosi_sirovo": len(kand_o), "odnosi_uzemljeno": len(uz_o),
                       "razlog": razlog})
    return True, sirovo_e, uzemljeni_e, sirovo_o, uzemljeni_o, delovi


def izvuci(blocks: Iterable[Any], *, persona=None) -> tuple[list[dict], list[dict]]:
    """(entiteti, odnosi) — LLM uzemljeni; fallback na determinističku osnovu.

    Kad spoljni model nije dostupan (isključen, bez ključa, pad, ili prazan/
    neuzemljen odgovor), vraća `entiteti.izvuci_entitete`/`izvuci_odnose`.
    """
    blocks = list(blocks)
    osnova_e = entiteti.izvuci_entitete(blocks)
    osnova_o = entiteti.izvuci_odnose(blocks, osnova_e)
    try:
        primenjiv, _se, uz_e, _so, uz_o, _delovi = _llm_izvuci(blocks, persona)
    except Exception:  # bilo kakav propust LLM puta → deterministička osnova
        log.warning("LLM entiteti pali, fallback na osnovu", exc_info=True)
        return osnova_e, osnova_o
    if not primenjiv or not uz_e:
        return osnova_e, osnova_o
    return uz_e, uz_o


def meri(blocks: Iterable[Any], *, persona=None) -> dict:
    """Dijagnostika: sirovo vs uzemljeno za entitete i odnose, ukupno i po delu."""
    blocks = list(blocks)
    try:
        primenjiv, se, uz_e, so, uz_o, delovi = _llm_izvuci(blocks, persona)
    except Exception:
        log.warning("LLM entiteti (meri) pali", exc_info=True)
        return {"model_zvan": False, "entiteti_sirovo": 0, "entiteti_uzemljeno": 0,
                "odnosi_sirovo": 0, "odnosi_uzemljeno": 0, "delovi": []}
    return {"model_zvan": primenjiv, "entiteti_sirovo": se,
            "entiteti_uzemljeno": len(uz_e), "odnosi_sirovo": so,
            "odnosi_uzemljeno": len(uz_o), "delovi": delovi}


def upisi(document, *, persona=None) -> dict[str, int]:
    """Izvuci (LLM ili osnova) i upiši — isti pisač kao `entiteti.upisi`."""
    kand_e, kand_o = izvuci(document.blocks.all(), persona=persona)
    return entiteti.upisi(document, kand_e=kand_e, kand_o=kand_o)
