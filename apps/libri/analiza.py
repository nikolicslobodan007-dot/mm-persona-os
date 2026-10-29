"""LLM analiza dosija — konkurentske hipoteze i otvorena pitanja (ADR-0031 4c, §9/§10).

Za razliku od tvrdnji (4a) i entiteta/odnosa (4b), §9/§10 su po prirodi INFERRED
(Canon §10.4): hipoteza i otvoreno pitanje su ZAKLJUČAK nad već izvučenim
činjenicama, ne doslovan isečak izvora. Zato ovde NEMA filtera doslovnog
uzemljenja (preklapanje reči) — sinteza preformuliše. Umesto toga tri brane:

1. Model vidi SAMO dosijeov OBSERVED materijal (tvrdnje, akteri, odnosi,
   kontradikcije) sa block_id-jevima — ne otvoreno znanje sveta.
2. Svaka hipoteza/pitanje mora da se OSLONI na bar jedan POSTOJEĆI block_id;
   izmišljene reference se bacaju, a stavka bez ijednog postojećeg oslonca se
   baca (ne sme da lebdi iznad korpusa).
3. Izlaz je jasno INFERRED (dosije §12 to već kaže; svaka stavka nosi oznaku);
   nema rute → sekcije ostaju „—" (deterministička osnova, Canon §21).

Ovo je SLABIJA garancija nego 4a/4b (ne može se tražiti doslovno uzemljenje za
sintezu) — zato je izlaz uvek označen kao LLM-izveden, nikad kao OBSERVED.

Spoljni poziv ide SAMO kroz F7 gateway (ADR-0009), svrha EXTRACT (deli rutu sa
ekstraktorom; bez novog enuma/migracije). Nema lokalnog šablona za ovu svrhu →
bez rute je rezultat prazan, ne izmišljen.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.libri import ekstrakt
from common import enums as E

log = logging.getLogger(__name__)

_MAX_TEKST = 600  # gornja granica dužine jedne hipoteze/pitanja (znakova)

_SISTEM = (
    "Ti si analitičar koji nad DATIM činjenicama (i samo njima) predlaže "
    "konkurentske hipoteze i otvorena pitanja na srpskom. Ne uvodi činjenice "
    "kojih nema u ulazu i ne pretražuj svoje znanje. Hipoteza je moguće "
    "objašnjenje koje se slaže sa delom datih činjenica; navedi i hipoteze koje "
    "se međusobno isključuju (konkurentske). Otvoreno pitanje je ono na koje dati "
    "materijal NE daje odgovor. Uz svaku stavku navedi 'oslonac' — listu "
    "block_id-jeva iz ulaza na koje se oslanja. Vrati ISKLJUČIVO JSON objekat "
    'oblika {"hipoteze":[{"tekst":"...","oslonac":["blk_..."]}],'
    '"pitanja":[{"tekst":"...","oslonac":["blk_..."]}]}. Bez objašnjenja.'
)


def _prompt(prikupljeno: dict[str, Any]) -> str:
    L = [f"Naslov: {prikupljeno.get('naslov', '')}", "", "Tvrdnje:"]
    for t in prikupljeno.get("tvrdnje", []):
        rep = f"{t.get('subject', '')} {t.get('relacija', '')} {t.get('vrednost', '')}".strip()
        L.append(f"- [{t.get('block_id', '')}] {rep}")
    akteri = prikupljeno.get("akteri", [])
    if akteri:
        L.append("Akteri: " + ", ".join(f"{a['name']} ({a['kind']})" for a in akteri))
    odnosi = prikupljeno.get("odnosi", [])
    if odnosi:
        L.append("Odnosi:")
        for r in odnosi:
            L.append(f"- {r['subject']} -[{r['tip']}]-> {r['object']}")
    kontr = prikupljeno.get("kontradikcije", [])
    if kontr:
        L.append("Nestabilne tvrdnje (protivrečnost): "
                 + ", ".join(k["subject"] for k in kontr))
    return "\n".join(L)


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

    def _stavke(kljuc: str) -> list[dict]:
        out = []
        for r in data.get(kljuc, []) or []:
            if not isinstance(r, dict):
                continue
            tekst = str(r.get("tekst", "")).strip()
            osl = r.get("oslonac", [])
            osl = ([str(x).strip() for x in osl if str(x).strip()]
                   if isinstance(osl, list) else [])
            if tekst:
                out.append({"tekst": tekst, "oslonac": osl})
        return out

    return _stavke("hipoteze"), _stavke("pitanja")


def _uzemlji(stavke: list[dict], validni_blokovi: set[str]) -> list[dict]:
    """Zadrži stavke sa bar jednim POSTOJEĆIM block_id osloncem; filtriraj izmišljene."""
    out: list[dict] = []
    vidjeno: set[str] = set()
    for s in stavke:
        osl = [b for b in s["oslonac"] if b in validni_blokovi]
        if not osl:
            continue  # sve reference izmišljene / nijedna ne postoji → baca se
        tekst = s["tekst"][:_MAX_TEKST]
        kljuc = tekst.lower()
        if kljuc in vidjeno:
            continue
        vidjeno.add(kljuc)
        out.append({"tekst": tekst, "oslonac": list(dict.fromkeys(osl))})
    return out


def _iz_teksta(text: str, validni_blokovi) -> tuple[list[dict], list[dict]]:
    """Odgovor modela → (uzemljene hipoteze, uzemljena pitanja). Bez mreže i baze."""
    vb = set(validni_blokovi)
    h, p = _parse(text)
    return _uzemlji(h, vb), _uzemlji(p, vb)


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


def _llm_analiza(prikupljeno: dict, validni_blokovi, persona=None):
    """(primenjiv, hipoteze, pitanja, razlog).

    primenjiv=False → nema spoljne rute ili nema nijedne tvrdnje → prazno
    (sekcije ostaju „—"). Pad poziva → prazne liste, ali primenjiv=True.
    """
    from apps.llm_gateway import gateway

    rute = ekstrakt._spoljne_rute(persona)
    if not rute:
        return False, [], [], "no_route"
    if not prikupljeno.get("tvrdnje"):
        return False, [], [], "prazno"  # nema šta da se analizira
    tekst, razlog = _pozovi(gateway, rute, _prompt(prikupljeno), persona)
    if tekst is None:
        return True, [], [], razlog
    h, p = _iz_teksta(tekst, validni_blokovi)
    return True, h, p, razlog


def analiza(prikupljeno: dict, validni_blokovi, *, persona=None) -> dict[str, list]:
    """{'hipoteze': [...], 'pitanja': [...]} — prazno kad nema rute/modela (fallback)."""
    try:
        primenjiv, h, p, _r = _llm_analiza(prikupljeno, validni_blokovi, persona)
    except Exception:  # bilo kakav propust LLM puta → prazno (deterministička osnova)
        log.warning("LLM analiza dosija pala, fallback na prazno", exc_info=True)
        return {"hipoteze": [], "pitanja": []}
    if not primenjiv:
        return {"hipoteze": [], "pitanja": []}
    return {"hipoteze": h, "pitanja": p}


def meri(prikupljeno: dict, validni_blokovi, *, persona=None) -> dict:
    """Dijagnostika: da li je model zvan i koliko hipoteza/pitanja prođe brane."""
    try:
        primenjiv, h, p, razlog = _llm_analiza(prikupljeno, validni_blokovi, persona)
    except Exception:
        log.warning("LLM analiza (meri) pala", exc_info=True)
        return {"model_zvan": False, "hipoteze": 0, "pitanja": 0, "razlog": "greška"}
    return {"model_zvan": primenjiv, "hipoteze": len(h), "pitanja": len(p),
            "razlog": razlog}
