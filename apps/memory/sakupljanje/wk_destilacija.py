"""WK — destilacija (tekst → veština na srpskom).

Treći sloj „Sakupljenih vrata": dohvat (wk_dohvat) donese ČIST TEKST, a ovde ga
destilujemo u veštinu u formatu korpusa: {ime, koraci, napomene, pouzdanost}.

NAČELO — DESTILACIJA, NE PREPIS. Agent ne sme da nalepi izvorni tekst kao korake.
Izvlači POSTUPAK (šta uraditi, redom), svojim rečima, na srpskom (latinica sa
dijakritikom). `napomene` uvek nose trag porekla: „Destilovano iz <izvor> — ne prepis."

Arhitektura (isti obrazac kao Libri): DETERMINISTIČKA OSNOVA + LLM POJAČALO.
- Deterministički (ovde, 100% testirano bez kvote): sklapanje prompta, parsiranje
  i VALIDACIJA LLM odgovora, odbacivanje prepisa/ćirilice/praznog, pakovanje u
  PREDLOG (status koji čeka Meta-reviziju + GO pre upisa u bazu).
- LLM pojačalo: jedini korak koji stvarno „piše" korake je `llm(prompt)->str`.
  Ubrizgava se споља (F7 Gateway u produkciji, lažni LLM u testu) → ne zavisi od
  kvote da bi se logika dokazala.

Gating (nacrt „Sakupljeno"): izlaz je uvek status=PREDLOG. Ništa ne ide u bazu
veština dok ga Meta-revizija ne prihvati (GO) i dok se ne prođe CONTROLLED_LIVE.
"""

from __future__ import annotations

import json
import re

# Status životnog ciklusa veštine u „Sakupljenim vratima".
PREDLOG = "PREDLOG"          # destilovano, čeka reviziju
PRIHVACENO = "PRIHVACENO"    # prošlo Meta-reviziju (GO)
ODBIJENO = "ODBIJENO"

# Ćirilica — korpus je latinica; ćirilični odgovor je greška destilacije.
_CIRILICA = re.compile(r"[Ѐ-ӿ]")
# „Prepis" heuristika: predugačak korak = verovatno nalepljen izvorni tekst.
_MAKS_DUZINA_KORAKA = 320


def napravi_prompt(tekst: str, *, izvor_opis: str, maks_vestina: int = 3) -> str:
    """Deterministički sklopi prompt za LLM. Isti ulaz → isti prompt (reproducibilno).

    Prompt nalaže: srpski (latinica + dijakritika), DESTILUJ postupak (ne prepisuj),
    strogi JSON izlaz u formatu korpusa. `izvor_opis` ulazi u `napomene` svake veštine.
    """
    tekst = (tekst or "").strip()
    return (
        "Ti si bibliotekar veština u srpskoj AI korporaciji. Iz DATOG TEKSTA izvuci "
        "praktičan POSTUPAK koji agent može da izvede — šta uraditi, redom.\n\n"
        "PRAVILA:\n"
        "- Piši na srpskom, latinicom, sa dijakritikom (č, ć, š, ž, đ). NIKAD ćirilicom.\n"
        "- DESTILUJ, ne prepisuj: koraci su tvoje jasne instrukcije, ne rečenice iz izvora.\n"
        "- Svaki korak je kratka naredba (jedan postupak). Najmanje 2, najviše 9 koraka.\n"
        f"- Izvuci najviše {maks_vestina} veština. Ako tekst nema upotrebljiv postupak, vrati [].\n"
        "- `pouzdanost` 0.0–1.0: koliko si siguran da je postupak tačan i potpun.\n\n"
        "IZLAZ — isključivo JSON niz, bez ijedne reči van njega:\n"
        '[{"ime": "...", "koraci": ["...", "..."], '
        f'"napomene": "Destilovano iz {izvor_opis} — ne prepis.", '
        '"pouzdanost": 0.7}]\n\n'
        "TEKST:\n"
        f"{tekst}\n"
    )


def _izvuci_json(sirovo: str) -> list | None:
    """Nađi JSON niz u LLM odgovoru (toleriše ```json ... ``` i uvodni tekst)."""
    s = (sirovo or "").strip()
    # skini code-fence ako ga ima
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    # prvi [ ... poslednji ]
    i, j = s.find("["), s.rfind("]")
    if i == -1 or j == -1 or j < i:
        return None
    try:
        podaci = json.loads(s[i : j + 1])
    except json.JSONDecodeError:
        return None
    return podaci if isinstance(podaci, list) else None


def _ocisti_vestinu(v: dict, *, izvor_opis: str) -> dict | None:
    """Validuj i očisti jednu veštinu; vrati čist dict ili None ako je neispravna."""
    if not isinstance(v, dict):
        return None
    ime = str(v.get("ime", "")).strip()
    koraci_ulaz = v.get("koraci")
    if not ime or not isinstance(koraci_ulaz, list):
        return None

    koraci: list[str] = []
    for k in koraci_ulaz:
        t = str(k).strip()
        if not t:
            continue
        if len(t) > _MAKS_DUZINA_KORAKA:   # prepis, ne destilacija
            return None
        if _CIRILICA.search(t):            # mora latinica
            return None
        koraci.append(t)
    if len(koraci) < 2:                    # postupak je bar dva koraka
        return None
    if _CIRILICA.search(ime):
        return None

    try:
        pouzdanost = float(v.get("pouzdanost", 0.6))
    except (TypeError, ValueError):
        pouzdanost = 0.6
    pouzdanost = max(0.0, min(1.0, pouzdanost))

    # `napomene` uvek nose trag porekla — determinističko, ne verujemo LLM-u za ovo.
    napomene = f"Destilovano iz {izvor_opis} — ne prepis."
    return {"ime": ime, "koraci": koraci, "napomene": napomene,
            "pouzdanost": round(pouzdanost, 2)}


def parsiraj_odgovor(sirovo: str, *, izvor_opis: str) -> dict:
    """LLM sirov tekst → {'ok', 'vestine'|'razlog'}. Deterministički, bez mreže."""
    niz = _izvuci_json(sirovo)
    if niz is None:
        return {"ok": False, "razlog": "odgovor nije JSON niz"}
    vestine = []
    for v in niz:
        cista = _ocisti_vestinu(v, izvor_opis=izvor_opis)
        if cista is not None:
            vestine.append(cista)
    if not vestine:
        return {"ok": False, "razlog": "nijedna veština nije prošla validaciju"}
    return {"ok": True, "vestine": vestine}


def destiluj(tekst: str, *, izvor_opis: str, llm, maks_vestina: int = 3) -> dict:
    """Orkestracija: tekst → PREDLOG veština (status koji čeka Meta-reviziju).

    `llm`: callable(prompt:str) -> str (F7 Gateway u produkciji; lažni u testu).
    Vraća {'ok', 'status', 'vestine'|'razlog'}. Status je UVEK PREDLOG — gating
    (GO + CONTROLLED_LIVE) je zaseban korak, ne upisujemo u bazu odavde.
    """
    tekst = (tekst or "").strip()
    if len(tekst) < 40:
        return {"ok": False, "razlog": "premalo teksta za destilaciju"}
    prompt = napravi_prompt(tekst, izvor_opis=izvor_opis, maks_vestina=maks_vestina)
    try:
        sirovo = llm(prompt)
    except Exception as e:  # pojačalo palo (kvota/mreža) — osnova ostaje ispravna
        return {"ok": False, "razlog": f"LLM nedostupan: {e}"}
    rez = parsiraj_odgovor(sirovo or "", izvor_opis=izvor_opis)
    if not rez["ok"]:
        return rez
    return {"ok": True, "status": PREDLOG, "vestine": rez["vestine"]}


if __name__ == "__main__":
    # Ručni pregled sa lažnim LLM-om (bez kvote).
    def lazni_llm(_prompt: str) -> str:
        return json.dumps([{
            "ime": "Kako napisati hladni mejl",
            "koraci": ["Istraži primaoca i njegovu firmu.",
                       "Personalizuj prvu rečenicu konkretnim detaljem.",
                       "Daj jedan jasan poziv na akciju."],
            "napomene": "ignoriše se — prepisujemo deterministički",
            "pouzdanost": 0.75,
        }], ensure_ascii=False)

    out = destiluj("Prvo istraži primaoca. Zatim personalizuj uvod. Na kraju jasan CTA. "
                   "Ovo je dovoljno dugačak tekst da prođe prag destilacije.",
                   izvor_opis="primer.test/clanak", llm=lazni_llm)
    print(json.dumps(out, ensure_ascii=False, indent=1))
