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
  - **Razvrstavanje po sektorima je zasad tabela reči**, ne model. To je
    svesna privremena stvar i piše ovde, a ne u ADR-u kao da je trajno
    rešenje: kad direktor bude birala sektor modelom, menja se samo
    `odredi_sektor`.
  - **Posao se izvršava odmah, u istom zahtevu.** Lanac traje
    desetak sekundi; kad bude duži, ide u red poslova. Do tada je bolje da čovek
    sačeka nego da ne vidi ishod.
"""

from __future__ import annotations

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
            {"handler": "plan.note", "description": "Preuzmi gotov posao",
             "input": {"note": f"Nacrt preuzet od {izvrsilac.public_id}."}},
        ]
    return [
        {"handler": "org.delegate", "description": f"Zadaj: {sef.display_name}",
         "input": {"to": sef.public_id, "goal": tema, "steps": unutra}},
        {"handler": "plan.note", "description": "Javi čoveku ishod",
         "input": {"note": f"Posao vođen preko {sef.public_id}."}},
    ]


def _nacrt_iz_lanca(plan: AgentPlan, dubina: int = 0) -> dict | None:
    """Traži izlaz koraka `content.draft` kroz ceo lanac delegiranja.

    Ide po `waiting_for_plan`, koji `advance` upisuje PRE nego što izvršilac
    krene — zato je veza pouzdana i kad je posao već gotov.
    """
    if dubina > 5:
        return None
    for s in plan.steps.order_by("sequence"):
        izlaz = s.output_json or {}
        if (s.input_json or {}).get("handler") == "content.draft" and izlaz.get("item"):
            return izlaz
        dete = izlaz.get("waiting_for_plan")
        if dete:
            d = AgentPlan.objects.filter(public_id=dete).first()
            if d is not None:
                nadjeno = _nacrt_iz_lanca(d, dubina + 1)
                if nadjeno:
                    return nadjeno
    return None


def _odgovor(plan: AgentPlan, sef: Persona, izvrsilac: Persona | None) -> str:
    """Šta direktor javlja čoveku kad se lanac vrati."""
    from common import enums as E

    ko = (izvrsilac or sef).display_name
    if plan.status == E.PlanStatus.COMPLETED.value:
        nacrt = _nacrt_iz_lanca(plan)
        if nacrt:
            return (f"Urađeno. Zadala sam {sef.display_name}, posao je uradio "
                    f"{ko}.\n\n{nacrt.get('tekst', '')}")
        return (f"Posao je završen preko {sef.display_name}, ali nacrt nije "
                f"stigao do mene. Plan: {plan.public_id}.")
    razlog = plans.failure_reason(plan) or plan.status
    return (f"Nije urađeno. Zadala sam {sef.display_name}, a posao je stao: "
            f"{razlog}. Plan: {plan.public_id}.")


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

    kod = odredi_sektor(telo)
    sef = _sef_sektora(direktor, kod)
    if sef is None:
        raise RazgovorError(
            f"{direktor.public_id} nema potčinjenog koji vodi sektor {kod}.")
    zasto = can_delegate(direktor, sef)
    if zasto:
        raise RazgovorError(zasto)
    izvrsilac = _izvrsilac(sef)

    plan = plans.start(direktor, telo[:2000], _koraci(telo, sef, izvrsilac),
                       actor=actor)
    audit.record("razgovor.zadato", persona=direktor,
                 details={"razgovor": str(razgovor.id), "plan": plan.public_id,
                          "sektor": kod, "sef": sef.public_id,
                          "izvrsilac": getattr(izvrsilac, "public_id", ""),
                          "actor": actor})
    plans.advance(plan)
    plan.refresh_from_db()

    odgovor = Poruka.objects.create(
        razgovor=razgovor, autor=Poruka.OD_AGENTA, autor_ref=direktor.public_id,
        telo=_odgovor(plan, sef, izvrsilac), plan=plan)
    razgovor.save(update_fields=["updated_at"])  # auto_now; `.update()` ga ne dira
    return odgovor
