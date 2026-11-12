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
           _tacno_tri_reda),
    Slucaj("srpski", "Srpski jezik", _SR,
           "Napiši jednu rečenicu o jesenjoj berbi grožđa.",
           _ima_dijakritiku),
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


def pokreni(specovi: list[str], slucajevi: list[Slucaj], *, persona,
           purpose: E.LLMPurpose = E.LLMPurpose.CONTENT_DRAFT,
           now: datetime | None = None) -> list[Rezultat]:
    from apps.content.service import operator_run
    from apps.llm_gateway import gateway

    now = now or timezone.now()
    rez: list[Rezultat] = []
    for spec in specovi:
        ruta = ruta_za(spec, purpose)
        run = operator_run(persona, now)
        for s in slucajevi:
            t0 = time.monotonic()
            try:
                gen = gateway.generate(purpose, s.system, s.prompt,
                                       persona=persona, run=run, only=ruta)
                ms = int((time.monotonic() - t0) * 1000)
                rez.append(Rezultat(spec, s.kljuc, s.kategorija,
                                    bool(s.proveri(gen.text or "")),
                                    gen.input_tokens, gen.output_tokens, ms,
                                    gen.provider,
                                    uzorak=(gen.text or "").strip()[:120]))
            except Exception as e:  # noqa: BLE001 — pad rute je podatak, ne kraj
                ms = int((time.monotonic() - t0) * 1000)
                rez.append(Rezultat(spec, s.kljuc, s.kategorija, False, ms=ms,
                                    greska=f"{type(e).__name__}: {e}"[:80]))
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
