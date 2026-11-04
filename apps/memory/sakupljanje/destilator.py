"""Destilator veština — proizvoljan tekst → srpske veštine (kroz Gateway EXTRACT).

Jezgro je izvučeno iz `harvest_agency` (koji je destilovao .md definicije) da ga
dele i harvest i novi sakupljač (`sakupi`): isti sistem/prompt/parser i isti
filteri kvaliteta (bez ćirilice, koraci ≤320 znakova, min 2 koraka). Izvor je
sad svejedno — .md, web, OCR slike ili ASR klipa; ulaz je tekst, izlaz veštine
u formatu {ime, koraci, napomene, pouzdanost}.

`napomena` kaže ODAKLE je destilovano (za trag porekla); licenca se NE pogađa
ovde — to je stvar uvoza u korpus (ADR-0059: podrazumevano NEPOZNATA).
`--suvo` koristi lažni LLM (nula poziva, nula para) — za probu toka i CI.
"""

from __future__ import annotations

import json
import re

_CIRILICA = re.compile(r"[Ѐ-ӿ]")
_MAKS_DUZINA_KORAKA = 320  # duži „korak" je verovatno prepis, ne naš sažetak

_SISTEM = (
    "Ti si precizan bibliotekar veština u srpskoj AI korporaciji. Iz datog teksta "
    "izvlačiš konkretne, primenljive radne postupke. Vraćaš ISKLJUČIVO traženi JSON "
    "niz, na srpskom (latinica sa dijakritikom), bez ijedne reči van JSON-a."
)


def _prompt(naslov: str, opis: str, telo: str, maks: int) -> str:
    return (
        f"Izvor: {naslov}\n"
        f"Kratak opis: {opis}\n\n"
        "Iz sledećeg teksta izvuci najviše "
        f"{maks} konkretne veštine (radna postupka) koje agent može da primeni.\n"
        "Za svaku veštinu vrati objekat sa poljima:\n"
        '  "ime": kratak naslov veštine na srpskom (latinica),\n'
        '  "koraci": niz od 2 do 6 kratkih koraka, svaki jedna rečenica, NAŠIM rečima '
        "(sažetak postupka, NE prepis originala),\n"
        '  "pouzdanost": broj između 0 i 1.\n'
        "Pravila: sve na srpskom latinicom; bez ćirilice; bez engleskih rečenica; "
        "koraci kratki i jasni; ne prepisuj rečenice iz originala već ih sažmi svojim rečima. "
        "Ako tekst ne sadrži nijedan primenljiv postupak, vrati prazan niz [].\n"
        "Vrati ISKLJUČIVO JSON niz tih objekata, ništa drugo.\n\n"
        "--- TEKST ---\n"
        f"{telo}\n"
        "--- KRAJ ---"
    )


def parsiraj(sirovo: str, napomena: str, maks: int) -> list[dict]:
    """Sirov LLM izlaz → lista veština, uz filtere kvaliteta. Čista funkcija."""
    s = sirovo.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    i, j = s.find("["), s.rfind("]")
    if i == -1 or j == -1:
        return []
    try:
        podaci = json.loads(s[i:j + 1])
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for v in podaci:
        if not isinstance(v, dict):
            continue
        ime = str(v.get("ime", "")).strip()
        koraci = [str(k).strip() for k in v.get("koraci", []) if str(k).strip()]
        if not ime or len(koraci) < 2:
            continue
        if _CIRILICA.search(ime) or any(_CIRILICA.search(k) for k in koraci):
            continue
        if any(len(k) > _MAKS_DUZINA_KORAKA for k in koraci):
            continue
        try:
            pouzdanost = float(v.get("pouzdanost", 0.7))
        except (TypeError, ValueError):
            pouzdanost = 0.7
        pouzdanost = min(max(pouzdanost, 0.0), 1.0)
        out.append({"ime": ime, "koraci": koraci[:6], "napomene": napomena,
                    "pouzdanost": round(pouzdanost, 2)})
        if len(out) >= maks:
            break
    return out


def _lazni_llm(_sistem, prompt):
    """Suvi režim: deterministički odgovor, nula poziva ka Gateway-u."""
    naslov = "Primer veštine iz teksta"
    m = re.search(r"Izvor:\s*(.+)", prompt)
    if m:
        naslov = "Osnovni postupak — " + m.group(1).strip()[:40]
    return json.dumps([{
        "ime": naslov,
        "koraci": ["Pročitaj zahtev i razdvoji šta je hitno od šta je složeno.",
                   "Primeni pravilo struke i zabeleži šta si uradio.",
                   "Proveri rezultat pre nego što ga predaš dalje."],
        "pouzdanost": 0.6,
    }], ensure_ascii=False)


def napravi_llm(suvo: bool = False):
    """Pozvivo `llm(sistem, prompt)->str`; pamti poslednji Generation u `.last`."""
    if suvo:
        return _lazni_llm
    from apps.llm_gateway import gateway
    from common import enums as E

    def llm(sistem, prompt):
        g = gateway.generate(E.LLMPurpose.EXTRACT, sistem, prompt)
        llm.last = g  # type: ignore[attr-defined]
        return g.text
    llm.last = None  # type: ignore[attr-defined]
    return llm


def destiluj(telo: str, *, naslov: str = "", opis: str = "", napomena: str = "",
             maks: int = 4, llm=None, suvo: bool = False) -> dict:
    """Tekst → veštine. Ako LLM da 0 (a nije suvo), pokušaj još jednom (LLM varira).

    Vraća {"vestine": [...], "ul": tok, "iz": tok, "cena": centi, "etiketa": str}.
    """
    if llm is None:
        llm = napravi_llm(suvo)
    prompt = _prompt(naslov or "(bez naslova)", opis, telo, maks)

    def jedan():
        sirovo = llm(_SISTEM, prompt)
        g = None if suvo else getattr(llm, "last", None)
        return parsiraj(sirovo, napomena, maks), g

    vestine, g = jedan()
    ul, iz, cena = _tokeni(g)
    etiketa = "suvo" if suvo else (f"{g.provider}/{g.model}" if g else "?")
    if not vestine and not suvo:  # retry jednom
        vestine, g2 = jedan()
        u2, i2, c2 = _tokeni(g2)
        ul, iz, cena = ul + u2, iz + i2, cena + c2
        if g2 is not None:
            etiketa = f"{g2.provider}/{g2.model}"
    return {"vestine": vestine, "ul": ul, "iz": iz, "cena": cena, "etiketa": etiketa}


def _tokeni(g):
    if g is None:
        return 0, 0, 0
    return (g.input_tokens or 0), (g.output_tokens or 0), (g.amount_eur_cents or 0)
