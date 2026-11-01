"""manage.py harvest_agency — destiluje agency-agents .md definicije u srpske veštine.

Čita .md definicije specijalista (npr. korpus/izvori/agency-agents-security/*.md),
svaku provuče kroz F7 Gateway (purpose EXTRACT) i izvuče do N veština u našem formatu
{ime, koraci, napomene, pouzdanost} — na srpskom (latinica), NAŠ opis postupka, ne prepis.
Rezultat upisuje u korpus/vestine/<izlaz>.json i ispisuje cenu (tokeni, €¢) po fajlu i zbir.

Primeri:
  python manage.py harvest_agency --divizija security
  python manage.py harvest_agency --izvor-dir korpus/izvori/agency-agents-security \
      --izlaz korpus/vestine/agency-agents-security.json --maks-po-fajlu 3
  python manage.py harvest_agency --divizija security --suvo   # bez troška (lažni LLM)

`--suvo` koristi ugrađeni lažni LLM (nula poziva, nula para) — za probu toka i CI.
Pravi rad zove Gateway, pa staje pod njegove dozvole/rutu/zapis (ADR-0086).
"""

from __future__ import annotations

import json
import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

_CIRILICA = re.compile(r"[Ѐ-ӿ]")
_MAKS_DUZINA_KORAKA = 320  # duži „korak" je verovatno prepis, ne naš sažetak

_SISTEM = (
    "Ti si precizan bibliotekar veština u srpskoj AI korporaciji. Iz opisa jednog "
    "specijaliste izvlačiš konkretne, primenljive radne postupke. Vraćaš ISKLJUČIVO "
    "traženi JSON niz, na srpskom (latinica sa dijakritikom), bez ijedne reči van JSON-a."
)


def _prompt(naslov: str, opis: str, telo: str, maks: int) -> str:
    return (
        f"Specijalista: {naslov}\n"
        f"Kratak opis: {opis}\n\n"
        "Iz sledećeg opisa izvuci najviše "
        f"{maks} konkretne veštine (radna postupka) koje agent može da primeni.\n"
        "Za svaku veštinu vrati objekat sa poljima:\n"
        '  "ime": kratak naslov veštine na srpskom (latinica),\n'
        '  "koraci": niz od 2 do 6 kratkih koraka, svaki jedna rečenica, NAŠIM rečima '
        "(sažetak postupka, NE prepis originala),\n"
        '  "pouzdanost": broj između 0 i 1.\n'
        "Pravila: sve na srpskom latinicom; bez ćirilice; bez engleskih rečenica; "
        "koraci kratki i jasni; ne prepisuj rečenice iz originala već ih sažmi svojim rečima. "
        "Vrati ISKLJUČIVO JSON niz tih objekata, ništa drugo.\n\n"
        "--- OPIS ---\n"
        f"{telo}\n"
        "--- KRAJ ---"
    )


def _sk_frontmatter(tekst: str) -> tuple[str, str, str]:
    """Vrati (name, description, telo_bez_frontmatter) iz .md sa YAML zaglavljem."""
    name, desc = "", ""
    telo = tekst
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", tekst, re.S)
    if m:
        glava, telo = m.group(1), m.group(2)
        for red in glava.splitlines():
            if red.lower().startswith("name:"):
                name = red.split(":", 1)[1].strip().strip('"')
            elif red.lower().startswith("description:"):
                desc = red.split(":", 1)[1].strip().strip('"')
    return name, desc, telo.strip()


def _parsiraj(sirovo: str, izvor_opis: str, maks: int) -> list[dict]:
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
    nap = f"Destilovano iz agency-agents/{izvor_opis} (MIT) — naš opis postupka, ne prepis."
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
        out.append({"ime": ime, "koraci": koraci[:6], "napomene": nap,
                    "pouzdanost": round(pouzdanost, 2)})
        if len(out) >= maks:
            break
    return out


def _lazni_llm(_sistem, prompt):
    """Suvi režim: deterministički odgovor, nula poziva ka Gateway-u."""
    naslov = "Primer veštine iz opisa"
    m = re.search(r"Specijalista:\s*(.+)", prompt)
    if m:
        naslov = "Osnovni postupak — " + m.group(1).strip()[:40]
    return json.dumps([{
        "ime": naslov,
        "koraci": ["Pročitaj zahtev i razdvoji šta je hitno od šta je složeno.",
                   "Primeni pravilo struke i zabeleži šta si uradio.",
                   "Proveri rezultat pre nego što ga predaš dalje."],
        "pouzdanost": 0.6,
    }], ensure_ascii=False)


class Command(BaseCommand):
    help = "Destiluje agency-agents .md definicije u srpske veštine (kroz Gateway)."

    def add_arguments(self, p):
        p.add_argument("--divizija", help="naziv divizije (npr. security) — izvor i izlaz po njoj")
        p.add_argument("--izvor-dir", help="direktorijum sa .md definicijama")
        p.add_argument("--izlaz", help="putanja izlaznog .json (korpus/vestine/...)")
        p.add_argument("--maks-po-fajlu", type=int, default=3)
        p.add_argument("--maks-znakova", type=int, default=9000,
                       help="kapa dužine tela (kontrola troška)")
        p.add_argument("--suvo", action="store_true", help="bez troška (lažni LLM)")

    def handle(self, *args, **o):
        baza = getattr(settings, "BASE_DIR", os.getcwd())
        div = o.get("divizija")
        izvor = o.get("izvor_dir") or (
            os.path.join("korpus", "izvori", f"agency-agents-{div}") if div else None)
        izlaz = o.get("izlaz") or (
            os.path.join("korpus", "vestine", f"agency-agents-{div}.json") if div else None)
        if not izvor or not izlaz:
            raise CommandError("Daj --divizija ILI (--izvor-dir i --izlaz).")
        izvor_abs = izvor if os.path.isabs(izvor) else os.path.join(baza, izvor)
        izlaz_abs = izlaz if os.path.isabs(izlaz) else os.path.join(baza, izlaz)
        if not os.path.isdir(izvor_abs):
            raise CommandError(f"Nema direktorijuma: {izvor_abs}")

        fajlovi = sorted(f for f in os.listdir(izvor_abs)
                         if f.endswith(".md") and f.lower() not in ("source.md", "readme.md"))
        if not fajlovi:
            raise CommandError(f"Nema .md definicija u {izvor_abs}")

        if o.get("suvo"):
            llm = _lazni_llm
        else:
            from apps.llm_gateway import gateway
            from common import enums as E

            def llm(sistem, prompt):
                g = gateway.generate(E.LLMPurpose.EXTRACT, sistem, prompt)
                llm.last = g  # type: ignore[attr-defined]
                return g.text
            llm.last = None  # type: ignore[attr-defined]

        maks = o["maks_po_fajlu"]
        sve: list[dict] = []
        zbir_ul = zbir_iz = zbir_cena = 0
        for f in fajlovi:
            tekst = open(os.path.join(izvor_abs, f), encoding="utf-8").read()
            name, desc, telo = _sk_frontmatter(tekst)
            telo = telo[:o["maks_znakova"]]
            sirovo = llm(_SISTEM, _prompt(name or f, desc, telo, maks))
            div_ime = div or os.path.basename(izvor_abs.rstrip("/"))
            vestine = _parsiraj(sirovo, f"{div_ime}/{f}", maks)
            sve.extend(vestine)
            g = getattr(llm, "last", None)
            if g is not None:
                zbir_ul += g.input_tokens or 0
                zbir_iz += g.output_tokens or 0
                zbir_cena += g.amount_eur_cents or 0
                dij = (f"  [{g.provider}/{g.model}] ul {g.input_tokens} / izl "
                       f"{g.output_tokens} tok · {g.amount_eur_cents}¢")
            else:
                dij = "  [suvo]"
            self.stdout.write(f"{f:48} → {len(vestine)} veština{dij}")

        os.makedirs(os.path.dirname(izlaz_abs), exist_ok=True)
        with open(izlaz_abs, "w", encoding="utf-8") as fh:
            json.dump(sve, fh, ensure_ascii=False, indent=2)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"UPISANO {len(sve)} veština → {izlaz}"))
        if not o.get("suvo"):
            self.stdout.write(
                f"CENA: ulaz {zbir_ul} tok, izlaz {zbir_iz} tok, ukupno {zbir_cena}¢ "
                f"({zbir_cena / 100:.2f} €) za {len(fajlovi)} definicija.")
