"""WK Model Benchmark — meri kvalitet-po-ceni modela po tipu zadatka (ADR-0150).

Poenta: za 300+ agenata izbor modela je 100× razlika u ceni, ali jeftin model
koji ne prolazi je bezvredan. Zato se NE bira unapred — meri se po kategoriji:
koji je NAJJEFTINIJI model koji i dalje PROLAZI.

Motor koristi postojeći gateway: `generate(only=ruta)` forsira tačan model
(ADR-0011), a `Generation` vraća tokene po pozivu. Cena se računa iz REALNIH
cena po milion tokena (proverene 12.11.2026), ne iz DB rute, da izveštaj bude
tačan nezavisno od konfiguracije.

Provera je zasad DETERMINISTIČKA (JSON parsira, dijakritika, format, broj) —
bez LLM-sudije; sudija je sledeći slajs.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from common import enums as E

#: Realne cene (USD po 1M tokena: ulaz, izlaz), proverene 12.11.2026. Ključ je
#: `provider:model_key`. Nepoznat model → cena 0 i napomena u izveštaju.
CENE_USD_1M: dict[str, tuple[float, float]] = {
    "anthropic:claude-haiku-5.5": (0.10, 0.50),
    "anthropic:claude-sonnet-5.5": (2.00, 10.00),
    "anthropic:claude-sonnet-5": (2.00, 10.00),
    "anthropic:claude-opus-5.5": (4.00, 20.00),
    "openai:gpt-5.4-mini": (0.75, 4.50),
    "openai:gpt-5-nano": (0.05, 0.40),
    "google:gemini-3.8-flash": (0.75, 3.75),
    "google:gemini-4-argon": (2.00, 10.00),
    "meta:llama-4-scout": (0.10, 0.30),
    "meta:llama-4-maverick": (0.27, 0.85),
    "xai:grok-4.7": (2.00, 6.00),
    "xai:grok-4.1-fast": (0.20, 0.50),
    "openrouter:qwen/qwen3.7-flash": (0.03, 0.13),
    "google:gemini-flash-latest": (0.75, 3.75),
}


def cena_usd(spec: str, tin: int, tout: int) -> float:
    ci, co = CENE_USD_1M.get(spec, (0.0, 0.0))
    return tin / 1_000_000 * ci + tout / 1_000_000 * co


# ----------------------------------------------------------------- slučajevi

@dataclass(frozen=True)
class Slucaj:
    kljuc: str
    kategorija: str
    system: str
    prompt: str
    proveri: Callable[[str], bool]
    sudija: str = ""


def _json_tip(tekst: str, dozvoljeni: set[str]) -> bool:
    m = re.search(r"\{.*\}", tekst or "", re.DOTALL)
    if not m:
        return False
    try:
        d = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return False
    return str(d.get("tip", "")).lower() in dozvoljeni


def _ima_dijakritiku(tekst: str) -> bool:
    return any(z in (tekst or "") for z in "čćšžđ")


def _tacno_tri_reda(tekst: str) -> bool:
    redovi = [r for r in (tekst or "").strip().splitlines() if r.strip()]
    return len(redovi) == 3


def _sadrzi(tekst: str, *sta: str) -> bool:
    t = (tekst or "").lower()
    return all(s.lower() in t for s in sta)


_SR = "Piši isključivo na srpskom, latinica sa dijakriticima (č, ć, š, ž, đ)."

SLUCAJEVI: list[Slucaj] = [
    Slucaj("klasifikacija", "CRM/JSON", _SR,
           "Klasifikuj firmu u tačno jedan tip: kupac, dobavljac ili konkurent. "
           "Vrati SAMO JSON oblika {\"tip\": \"...\"}. "
           "Firma: 'Vinarija koja od nas kupuje drvene gajbe.'",
           lambda t: _json_tip(t, {"kupac", "dobavljac", "konkurent"})),
    Slucaj("ekstrakcija", "CRM/JSON", _SR,
           "Iz teksta izvuci ime i grad kao JSON {\"ime\": \"...\", \"grad\": "
           "\"...\"}. Vrati samo JSON. Tekst: 'Marko Jović iz Novog Sada javio "
           "se povodom isporuke.'",
           lambda t: _sadrzi(t, "marko") and _sadrzi(t, "nov", "sad")),
    Slucaj("format-tri", "Format", _SR,
           "Nabroj tačno TRI razloga zašto je drvena ambalaža dobra za vino. "
           "Svaki razlog u novom redu, bez uvoda i bez numeracije.",
           _tacno_tri_reda,
           sudija="Tri razloga na ispravnom, prirodnom standardnom srpskom; "
                  "bez izmišljenih ili nestandardnih reči."),
    Slucaj("srpski", "Srpski jezik", _SR,
           "Napiši jednu rečenicu o jesenjoj berbi grožđa.",
           _ima_dijakritiku,
           sudija="Jedna rečenica na standardnom srpskom o jesenjoj berbi "
                  "grožđa: gramatički i pravopisno ispravna, prirodna, bez "
                  "izmišljenih ili nestandardnih reči."),
    Slucaj("rezon", "Rezonovanje", _SR,
           "Imamo 12 vinarija, svaka naruči po 8 gajbi. Koliko gajbi ukupno? "
           "Vrati samo broj.",
           lambda t: "96" in (t or "")),
]


# ----------------------------------------------------------------- pokretanje

@dataclass
class Rezultat:
    spec: str
    kljuc: str
    kategorija: str
    uspeh: bool
    tin: int = 0
    tout: int = 0
    ms: int = 0
    provider: str = ""
    greska: str = ""
    uzorak: str = ""
    sud: str = ""
    sud_ok: bool | None = None


def ruta_za(spec: str, purpose: E.LLMPurpose):
    """`provider:model_key` → LLMRoute (napravi je ako ne postoji). Za poređenje
    je dovoljno da ruta postoji i da provajder ima ključ; cena ide iz CENE_USD_1M."""
    from apps.llm_gateway.models import LLMRoute

    provider, _, model_key = spec.partition(":")
    if not model_key:
        raise ValueError(f"Ruta mora biti oblika provider:model_key, dato: {spec!r}")
    ruta, _n = LLMRoute.objects.get_or_create(
        provider=provider, model_key=model_key, purpose=purpose.value,
        defaults={"name": f"bench {spec}", "priority": 500, "is_enabled": True,
                  "data_training_allowed": True,
                  "is_openai_compatible": provider != "anthropic",
                  "notes": "Napravljeno za WK Model Benchmark (ADR-0150)."})
    return ruta


#: Prolazne greške koje vredi ponoviti: rate-limit, preopterećenje, timeout.
_PROLAZNE = ("429", "500", "502", "503", "504", "timed out", "timeout",
             "NETWORK", "UNAVAILABLE")

JUDGE_SYSTEM = (
    "Ti si strog lektor standardnog srpskog jezika (latinica, sa dijakriticima). "
    "Ocenjuješ da li tekst zadovoljava dati kriterijum. Budi strog: izmišljena ili "
    "nestandardna reč, gramatička ili pravopisna greška znače pad. Odgovaraj "
    "isključivo kratkim JSON-om.")


def _pravopis_blok(izlaz: str) -> str:
    """Relevantna pravila Pravopisa za dati tekst (ADR-0120) — referenca sudiji.
    Best-effort: ako pravila nisu uvezena ili pretraga padne, vraća prazno."""
    try:
        from apps.content import recnik
        if not recnik.pravila_dostupna():
            return ""
        pravila = recnik.trazi_pravila(izlaz, granica=4)
    except Exception:  # noqa: BLE001 — pravila su pomoć, ne uslov
        return ""
    if not pravila:
        return ""
    redovi = [f"- т.{p.get('tacka', '?')} {p.get('sekcija', '')}: "
              f"{(p.get('tekst') or '').replace(chr(10), ' ')[:220]}" for p in pravila]
    return ("Reference iz Pravopisa srpskoga jezika (Matica srpska):\n"
            + "\n".join(redovi) + "\n\n")


def _strucni_blok(izlaz: str) -> str:
    """Relevantni stručni termini (pojmovnik, ADR-0154) kao referenca sudiji.
    Best-effort: ako pojmovnik nije uvezen ili pretraga padne, vraća prazno.
    Sprečava da sudija obori tačan domenski termin (npr. „buke" je vinski)."""
    try:
        from apps.content import pojmovnik
        if not pojmovnik.pojmovi_dostupni():
            return ""
        termini = pojmovnik.trazi_pojmove(izlaz, granica=5)
    except Exception:  # noqa: BLE001 — termini su pomoć, ne uslov
        return ""
    if not termini:
        return ""
    redovi = []
    for t in termini:
        syn = f" (= {', '.join(t['sinonimi'])})" if t.get("sinonimi") else ""
        redovi.append(f"- {t.get('termin', '')}{syn} [{t.get('domen', '')}]: "
                      f"{(t.get('definicija') or '')[:160]}")
    return ("Stručni termini (važeći, NE ispravljati ih kao greške):\n"
            + "\n".join(redovi) + "\n\n")


def _parsiraj_sud(tekst: str) -> tuple[bool, str]:
    m = re.search(r"\{.*\}", tekst or "", re.DOTALL)
    if not m:
        return False, ("sudija: nevažeći odgovor: " + (tekst or "")[:60])
    try:
        d = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return False, ("sudija: nevažeći JSON: " + (tekst or "")[:60])
    return bool(d.get("prolaz")), str(d.get("razlog", ""))[:200]


def oceni_sudijom(izlaz: str, kriterijum: str, *, persona, run, sudija_ruta,
                  purpose: E.LLMPurpose = E.LLMPurpose.CONTENT_DRAFT) -> tuple[bool, str]:
    """Oceni izlaz jačim modelom-sudijom, ukorenjeno u Pravopis (ADR-0055/0120).
    Vraća (prolaz, razlog). Pad sudije NE obara slučaj — vraća (True, 'sudija pao')."""
    from apps.llm_gateway import gateway

    prompt = (f"Kriterijum: {kriterijum}\n\n{_pravopis_blok(izlaz)}{_strucni_blok(izlaz)}"
              f"Tekst za ocenu:\n\"\"\"\n{izlaz}\n\"\"\"\n\n"
              "Vrati samo JSON {\"prolaz\": true/false, \"razlog\": \"kratko\"}.")
    try:
        gen = gateway.generate(purpose, JUDGE_SYSTEM, prompt,
                               persona=persona, run=run, only=sudija_ruta)
    except Exception as e:  # noqa: BLE001 — pad sudije ne obara slučaj
        return True, f"sudija pao: {type(e).__name__}"[:80]
    return _parsiraj_sud(gen.text or "")


def pokreni(specovi: list[str], slucajevi: list[Slucaj], *, persona,
           purpose: E.LLMPurpose = E.LLMPurpose.CONTENT_DRAFT,
           now: datetime | None = None, pokusaji: int = 3,
           pauza: float = 0.0, sudija: str = "",
           sudija_obara: bool = False) -> list[Rezultat]:
    """Za svaku rutu pusti slučajeve kroz gateway. Na 429 (rate-limit) ponovi
    do `pokusaji` puta sa rastućom pauzom; `pauza` je razmak između svih poziva
    (da besplatni nivoi ne throttluju). Pad rute je podatak, ne kraj."""
    from apps.content.service import operator_run
    from apps.llm_gateway import gateway

    now = now or timezone.now()
    sudija_ruta = ruta_za(sudija, purpose) if sudija else None
    rez: list[Rezultat] = []
    for spec in specovi:
        ruta = ruta_za(spec, purpose)
        run = operator_run(persona, now)
        for s in slucajevi:
            t0 = time.monotonic()
            gen, greska = None, ""
            for i in range(max(1, pokusaji)):
                try:
                    gen = gateway.generate(purpose, s.system, s.prompt,
                                           persona=persona, run=run, only=ruta)
                    greska = ""
                    break
                except Exception as e:  # noqa: BLE001 — pad rute je podatak
                    gen, greska = None, f"{type(e).__name__}: {e}"[:80]
                    if any(m in str(e) for m in _PROLAZNE) and i < pokusaji - 1:
                        time.sleep(4 * (i + 1))
                        continue
                    break
            ms = int((time.monotonic() - t0) * 1000)
            if gen is not None and not greska:
                tekst = gen.text or ""
                ok = bool(s.proveri(tekst))
                sud, sud_ok = "", None
                if ok and sudija_ruta is not None and s.sudija:
                    sud_ok, sud = oceni_sudijom(tekst, s.sudija, persona=persona,
                                                run=run, sudija_ruta=sudija_ruta,
                                                purpose=purpose)
                    if sudija_obara:
                        ok = ok and sud_ok
                rez.append(Rezultat(spec, s.kljuc, s.kategorija, ok,
                                    gen.input_tokens, gen.output_tokens, ms,
                                    gen.provider, uzorak=tekst.strip()[:120],
                                    sud=sud, sud_ok=sud_ok))
            else:
                rez.append(Rezultat(spec, s.kljuc, s.kategorija, False, ms=ms,
                                    greska=greska))
            if pauza:
                time.sleep(pauza)
    return rez


@dataclass
class Zbir:
    spec: str
    n: int = 0
    prosli: int = 0
    cena_usd: float = 0.0
    ms_zbir: int = 0
    greske: int = 0
    po_kategoriji: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def stopa(self) -> float:
        return self.prosli / self.n if self.n else 0.0

    @property
    def cena_po_uspehu(self) -> float:
        return self.cena_usd / self.prosli if self.prosli else float("inf")

    @property
    def ms_prosek(self) -> int:
        return self.ms_zbir // self.n if self.n else 0


def zbir(rezultati: list[Rezultat]) -> dict[str, Zbir]:
    out: dict[str, Zbir] = {}
    for r in rezultati:
        z = out.setdefault(r.spec, Zbir(r.spec))
        z.n += 1
        z.prosli += int(r.uspeh)
        z.cena_usd += cena_usd(r.spec, r.tin, r.tout)
        z.ms_zbir += r.ms
        z.greske += int(bool(r.greska))
        pk_p, pk_n = z.po_kategoriji.get(r.kategorija, (0, 0))
        z.po_kategoriji[r.kategorija] = (pk_p + int(r.uspeh), pk_n + 1)
    return out
