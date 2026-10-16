"""Razgovor čoveka sa direktorom, i posao koji iz njega nastaje. ADR-0105.

Do danas je svaki posao u ovoj firmi počinjao komandom u terminalu. Firma
nije imala ulazna vrata: čovek nije mogao ništa da zatraži, mogao je samo da
pokrene ono što mu je neko unapred napisao.

Ovde se ta rupa zatvara. Čovek napiše rečenicu direktoru; direktor je pretvara
u **posao**, spušta ga šefu sektora, šef izvršiocu, a ishod se vraća u istu
nit. Lanac je onaj koji već postoji (`plans.start`, `org.delegate`,
ADR-0017/0022) — nov je samo ulaz i povratak.

Tri granice, namerno:

  - **Direktor ne dobija nijednu novu dozvolu.** Delegiranje ne daje prava
    (ADR-0017); izvršilac radi sa svojim poverenjem. Nit ne dira prekidač
    spoljnih radnji i ne objavljuje ništa.
  - **Direktor prvo procenjuje** (ADR-0106): od poruke pravi nalog svojim
    rečima ili postavlja jedno pitanje ako posao ne može da se uradi kako je
    napisan. Procena je **dodatak, ne uslov** — bez modela radi kao pre.
  - **Sektor bez šefa ne obara posao.** Direktor ga daje upravi i to kaže u
    odgovoru. Posao koji stane zato što neko radno mesto nije popunjeno nije
    organizacija nego prepreka.
  - **Šef pregleda pre nego što vrati** (ADR-0108). Nije poštar: nacrt koji
    ne odgovara nalogu vraća sa primedbom i posao staje, a čovek vidi i
    razlog i nacrt koji nije prošao.
  - **Razvrstavanje po sektorima je zasad tabela reči**, ne model. To je
    svesna privremena stvar i piše ovde, a ne u ADR-u kao da je trajno
    rešenje: kad direktor bude birala sektor modelom, menja se samo
    `odredi_sektor`.
  - **Posao se izvršava odmah, u istom zahtevu.** Lanac traje
    desetak sekundi; kad bude duži, ide u red poslova. Do tada je bolje da čovek
    sačeka nego da ne vidi ishod.
"""

from __future__ import annotations

import json
import re

from api import audit
from apps.memory import embeddings
from apps.orchestration import plans
from apps.orchestration.models import AgentPlan, Poruka, Razgovor
from apps.personas.models import Persona
from apps.personas.org import can_delegate, department_of, subordinates

#: Reči koje vode ka sektoru. Poređenje ide nad `embeddings.normalize`, pa
#: dijakritika i velika slova ne smetaju. Prvi sektor koji ima pogodak nosi
#: posao; bez pogotka ide UPRAVA, jer direktor ima svog asistenta.
RECI_SEKTORA: dict[str, tuple[str, ...]] = {
    "MARKETING": ("tekst", "sadrzaj", "objav", "sajt", "post", "kampanj",
                  "copy", "naslov", "clanak", "blog", "drustven"),
    "PRODAJA": ("ponud", "kupac", "kupc", "prodaj", "izvoz", "cenovnik", "upit"),
    "ISTRAZIVANJE": ("istraz", "konkurenc", "trzist", "analiz", "uporedi",
                     "proveri", "pretraz"),
    "PODRSKA": ("podrsk", "reklamacij", "zalb", "korisnik"),
    "FINANSIJE": ("faktur", "marz", "trosk", "naplat", "avans", "porez"),
    "NABAVKA": ("dobavlj", "nabavk", "uzorak", "proizvodjac"),
    "LOGISTIKA": ("isporuk", "transport", "magacin", "posiljk", "rok"),
    "KVALITET": ("uskladj", "pravil", "oznak", "incident", "provera pre objave"),
    "RAZVOJ": ("kod", "program", "server", "sistem", "greska u aplikaciji"),
}
PODRAZUMEVANI_SEKTOR = "UPRAVA"

MAX_TELO = 4000


class RazgovorError(Exception):
    """Poruka nije mogla da postane posao — razlog je u poruci."""


#: ADR-0106 — direktor ne prosleđuje rečenicu nego od nje pravi nalog.
ODLUKA_SYSTEM = (
    "Ti si direktor korporacije u kojoj poslove obavljaju AI agenti. Čovek "
    "koji je vlasnik firme ti je napisao poruku. Tvoj posao NIJE da uradiš "
    "zadatak, nego da od poruke napraviš jasan nalog za sektor, ili da "
    "postaviš jedno pitanje ako poruka ne može da se izvrši kako jeste.\n"
    "Odgovaraš ISKLJUČIVO jednim JSON objektom, bez teksta oko njega:\n"
    '{"sektor": "<šifra>", "nalog": "<šta tačno treba uraditi>", '
    '"pitanje": "<jedno pitanje ili prazno>"}\n'
    "Pravila: ako postavljaš pitanje, `nalog` ostaje prazan i obrnuto. "
    "Pitaj samo kad bez odgovora posao ne može da se uradi — ne pitaj za "
    "sitnice koje možeš sama da odlučiš. `nalog` piši kao uputstvo "
    "izvršiocu, u jednoj do tri rečenice, na srpskom."
)

#: Koliko dugačko sme da bude ono što direktor vrati.
MAX_NALOG = 600
MAX_PITANJE = 300

_JSON = re.compile(r"\{.*\}", re.S)


def _procitaj_odluku(tekst: str, dozvoljeni: set[str]) -> dict:
    """Vadi odluku iz modelovog odgovora. Smeće se tiho odbacuje.

    Lokalni šablon (`apps/llm_gateway/local.py`) ne ume JSON i to je u redu:
    tada ovo vraća prazno, a direktor radi kao pre — po tabeli reči. Agent
    bez ključa ne sme da ostane bez posla, samo bez procene.
    """
    m = _JSON.search(tekst or "")
    if not m:
        return {}
    try:
        sirovo = json.loads(m.group(0))
    except (ValueError, TypeError):
        return {}
    if not isinstance(sirovo, dict):
        return {}
    sektor = str(sirovo.get("sektor", "")).strip().upper()
    return {
        "sektor": sektor if sektor in dozvoljeni else "",
        "nalog": str(sirovo.get("nalog", "")).strip()[:MAX_NALOG],
        "pitanje": str(sirovo.get("pitanje", "")).strip()[:MAX_PITANJE],
    }


def razmisli(direktor, telo: str, *, run=None) -> dict:
    """Direktorova procena poruke: koji sektor, koji nalog, ili koje pitanje.

    Nikad ne podiže grešku: ako model nije dostupan ili vrati nešto što nije
    JSON, vraća prazan rečnik i posao ide dalje po tabeli reči (ADR-0105).
    Procena je dodatak, ne uslov.
    """
    from apps.llm_gateway import gateway
    from apps.memory.context import _dosije_firme
    from common import enums as E

    spisak = ", ".join(sorted(RECI_SEKTORA) + [PODRAZUMEVANI_SEKTOR])
    # ADR-0107 — direktor pravi nalog znajući gde radi. Bez dosijea bi
    # izmišljala kupce i usluge kojih nema.
    dosije = _dosije_firme()
    prompt = ((f"{dosije}\n\n---\n\n" if dosije else "")
              + f"Sektori: {spisak}.\n\nPoruka vlasnika:\n{telo[:MAX_TELO]}")
    try:
        gen = gateway.generate(E.LLMPurpose.PLANNING, ODLUKA_SYSTEM, prompt,
                               persona=direktor, run=run,
                               brief={"tema": telo[:200], "jezik": "sr-Latn"})
    except Exception as e:  # noqa: BLE001 — procena ne sme da obori nalog
        audit.record("razgovor.procena.pala", persona=direktor,
                     details={"razlog": f"{type(e).__name__}: {e}"[:200]})
        return {}
    return _procitaj_odluku(gen.text, set(RECI_SEKTORA) | {PODRAZUMEVANI_SEKTOR})


def odredi_sektor(tekst: str) -> str:
    """Kom sektoru posao pripada. Tabela reči, privremeno (vidi zaglavlje)."""
    n = embeddings.normalize(tekst)
    for kod, reci in RECI_SEKTORA.items():
        if any(r in n for r in reci):
            return kod
    return PODRAZUMEVANI_SEKTOR


def _sef_sektora(direktor: Persona, kod: str) -> Persona | None:
    """Neposredni potčinjeni direktora koji vodi taj sektor."""
    for p in subordinates(direktor):
        d = department_of(p)
        if d is not None and d.code == kod:
            return p
    return None


def _izvrsilac(sef: Persona) -> Persona | None:
    """Prvi potčinjeni šefa, po javnom broju. Bez njega šef radi sam."""
    ljudi = sorted(subordinates(sef), key=lambda p: p.public_id)
    return ljudi[0] if ljudi else None


def _koraci(tema: str, sef: Persona, izvrsilac: Persona | None) -> list[dict]:
    """Koraci direktorovog plana: zadaj šefu, pa preuzmi gotov posao."""
    if izvrsilac is None:
        unutra = [{"handler": "content.draft", "description": "Napiši nacrt",
                   "input": {"tema": tema}}]
    else:
        unutra = [
            {"handler": "org.delegate",
             "description": f"Zadaj: {izvrsilac.display_name}",
             "input": {"to": izvrsilac.public_id, "goal": tema,
                       "steps": [{"handler": "content.draft",
                                  "description": "Napiši nacrt",
                                  "input": {"tema": tema}}]}},
            # ADR-0108 — šef ne preuzima nepročitano. Korak je njegov posao,
            # pa ga izvršava on, svojim poverenjem, u svom planu.
            {"handler": "content.review",
             "description": f"Pregledaj nacrt: {izvrsilac.display_name}",
             "input": {"nalog": tema}},
        ]
    return [
        {"handler": "org.delegate", "description": f"Zadaj: {sef.display_name}",
         "input": {"to": sef.public_id, "goal": tema, "steps": unutra}},
        {"handler": "plan.note", "description": "Javi čoveku ishod",
         "input": {"note": f"Posao vođen preko {sef.public_id}."}},
    ]


#: Oznaka AI persone na kraju nacrta (`content.service.disclosure_line`).
_POTPIS = re.compile(r"\n*—\s*[^\n]{1,80}·\s*AI persona\s*$")


def _bez_potpisa(tekst: str) -> str:
    """Potpis izvršioca ne ide u direktorovu poruku.

    Oznaka je obavezna (Canon §17) i ostaje na nacrtu u bazi i na svemu što
    izlazi napolje. Ovde se skida samo iz onoga što direktor prepisuje u nit:
    poruku u niti potpisuje direktor, pa bi inače u jednoj poruci stajala dva
    potpisa i čovek bi mislio da mu piše izvršilac.
    """
    return _POTPIS.sub("", tekst or "").rstrip()


#: Koliko nacrta staje u jednu poruku u niti. ADR-0109.
MAX_PRIKAZ = 4000


def _tekst_nacrta(nacrt: dict) -> str:
    """Ceo nacrt iz baze, ne skraćeni izlaz koraka. ADR-0109.

    Izlaz koraka `content.draft` nosi prvih 400 znakova — dovoljno za zapis,
    premalo za čoveka koji treba da presudi. Ako nacrta više nema u bazi,
    vraća se ono što je ostalo u koraku: bolje početak nego ništa.
    """
    from apps.content.models import ContentItem

    kljuc = nacrt.get("item") or ""
    item = ContentItem.objects.filter(pk=kljuc).first() if kljuc else None
    telo = (item.body if item is not None else "") or nacrt.get("tekst", "")
    return plans.shorten(_bez_potpisa(telo), MAX_PRIKAZ)


def _ishod(plan: AgentPlan, sef: Persona, izvrsilac: Persona | None) -> dict:
    """Ishod lanca, razložen na delove. ADR-0110.

    Jedan izvor za oboje: iz ovoga se gradi i zapis (`telo`) i prikaz
    (`delovi`), pa poruka u niti i tekst u bazi ne mogu da se raziđu.
    """
    from common import enums as E

    nacrt = plans.output_in_chain(plan, "content.draft") or {}
    d: dict = {"plan": plan.public_id, "nacrt": _tekst_nacrta(nacrt),
               "item": str(nacrt.get("item") or ""), "sef": sef.display_name,
               "izvrsilac": (izvrsilac or sef).display_name}

    if plan.status == E.PlanStatus.COMPLETED.value:
        if not nacrt:
            return d | {"stanje": "nejasno", "nacrt": "", "item": "",
                        "glava": (f"Posao je završen preko {sef.display_name}, ali "
                                  f"nacrt nije stigao do mene. "
                                  f"Plan: {plan.public_id}.")}
        ko = (izvrsilac or sef).display_name
        d |= {"stanje": "uradjeno",
              "glava": (f"Urađeno. Zadala sam {sef.display_name}, "
                        f"posao je uradio {ko}.")}
        # ADR-0108 — pregled se javlja samo ako ga je stvarno bilo. Bez modela
        # nacrt prolazi, ali direktor onda ne sme da tvrdi da je pregledan.
        pregled = plans.output_in_chain(plan, "content.review") or {}
        if pregled.get("presudio"):
            d["pregled"] = {"ko": sef.display_name,
                            "primedba": pregled.get("primedba") or "bez primedbe"}
        return d

    razlog = plans.failure_reason(plan) or plan.status
    return d | {"stanje": "stalo", "razlog": razlog,
                "glava": (f"Nije urađeno. Zadala sam {sef.display_name}, a posao "
                          f"je stao: {razlog}. Plan: {plan.public_id}.")}


def _tekst(d: dict) -> str:
    """Zapis poruke — isti sadržaj kao delovi, u rečenicama.

    Ovo je ono što ostaje u bazi i u izvozu. Konzola čita `delovi`, ali tekst
    mora da stoji sam za sebe: poruka bez prikaza i dalje mora da se razume.
    """
    redovi: list[str] = []
    if d.get("rezerva"):
        redovi.append(d["rezerva"])
    if d.get("nalog"):
        redovi.append(f"Zadatak koji sam prosledila: „{d['nalog']}“")
    if d.get("glava"):
        redovi.append(d["glava"])
    if d.get("pregled"):
        redovi.append(f"Pregled ({d['pregled']['ko']}): prihvaćeno — "
                      f"{d['pregled']['primedba']}")
    if d.get("nacrt"):
        if d.get("stanje") == "stalo":
            redovi.append("Nacrt koji nije prošao:")
        redovi.append(d["nacrt"])
    return "\n\n".join(redovi)


def posalji(razgovor: Razgovor, telo: str, *, actor: str) -> Poruka:
    """Čovekova poruka → posao → odgovor direktora u istoj niti.

    Vraća direktorovu poruku; čovekova je upisana pre nje i obe nose isti plan.
    """
    telo = (telo or "").strip()
    if not telo:
        raise RazgovorError("Prazna poruka.")
    if len(telo) > MAX_TELO:
        raise RazgovorError(f"Poruka je duža od {MAX_TELO} znakova.")

    direktor = razgovor.persona
    Poruka.objects.create(razgovor=razgovor, autor=Poruka.OD_COVEKA,
                          autor_ref=actor, telo=telo)

    # ADR-0106 — direktor prvo procenjuje. Ako model nije dostupan, procena
    # je prazna i sve ide kao pre (ADR-0105): tabela reči i doslovna tema.
    odluka = razmisli(direktor, telo)
    if odluka.get("pitanje") and not odluka.get("nalog"):
        audit.record("razgovor.pitanje", persona=direktor,
                     details={"razgovor": str(razgovor.id), "actor": actor})
        pitanje = Poruka.objects.create(
            razgovor=razgovor, autor=Poruka.OD_AGENTA,
            autor_ref=direktor.public_id, telo=odluka["pitanje"],
            delovi={"stanje": "pitanje", "glava": odluka["pitanje"]})
        razgovor.save(update_fields=["updated_at"])
        return pitanje

    tema = odluka.get("nalog") or telo
    kod = odluka.get("sektor") or odredi_sektor(telo)
    sef = _sef_sektora(direktor, kod)
    rezerva = ""
    if sef is None and kod != PODRAZUMEVANI_SEKTOR:
        # Sektor bez šefa nije razlog da posao stane: direktor ga daje svom
        # asistentu i to kaže čoveku. Izmereno 16.10.2026 — u organizaciji
        # zaista postoje sektori bez popunjenog mesta šefa.
        rezerva, kod = kod, PODRAZUMEVANI_SEKTOR
        sef = _sef_sektora(direktor, kod)
    if sef is None:
        raise RazgovorError(
            f"{direktor.public_id} nema nijednog potčinjenog kome bi zadala "
            f"posao (traženo: {rezerva or kod}).")
    zasto = can_delegate(direktor, sef)
    if zasto:
        raise RazgovorError(zasto)
    izvrsilac = _izvrsilac(sef)

    plan = plans.start(direktor, tema[:2000], _koraci(tema, sef, izvrsilac),
                       actor=actor)
    audit.record("razgovor.zadato", persona=direktor,
                 details={"razgovor": str(razgovor.id), "plan": plan.public_id,
                          "sektor": kod, "umesto": rezerva, "sef": sef.public_id,
                          "procenila": bool(odluka), "nalog": tema[:200],
                          "izvrsilac": getattr(izvrsilac, "public_id", ""),
                          "actor": actor})
    plans.advance(plan)
    plan.refresh_from_db()

    delovi = _ishod(plan, sef, izvrsilac)
    if odluka.get("nalog") and odluka["nalog"] != telo:
        delovi["nalog"] = odluka["nalog"]
    if rezerva:
        delovi["rezerva"] = (f"Sektor {rezerva} nema šefa, pa sam posao zadala "
                             "upravi.")
    odgovor = Poruka.objects.create(
        razgovor=razgovor, autor=Poruka.OD_AGENTA, autor_ref=direktor.public_id,
        telo=_tekst(delovi), plan=plan, delovi=delovi)
    razgovor.save(update_fields=["updated_at"])  # auto_now; `.update()` ga ne dira
    return odgovor
