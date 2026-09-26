"""Pisac zakrpe — model piše izmenu. ADR-0044 (druga polovina ADR-0041).

Do sada je zakrpu kucao čovek. Brif postoji (ADR-0041), kapije rade (ADR-0035),
grana se otvara (ADR-0043) — nedostajao je samo onaj ko piše.

## Zašto ovo nije petlja

Kapije se vrte u poslušniku, **van aplikacije**, jer aplikacija nikada ne sme da
dobije `docker.sock` (ADR-0038 §2). Petlja koja bi ovde čekala ishod kapija
morala bi ili da dobije Docker, ili da blokira radnika dok neko drugi meri. Zato
je ovo **jedan korak**, ne petlja:

    pokušaj → zakrpa → (poslušnik) kapije → sledeći pokušaj čita ishod iz brifa

Krug postoji, ali ga zatvara red, a ne `while`. Povratna informacija stiže kroz
brif, koji već nosi pale kapije i otvorene nalaze (ADR-0041 §4).

## Tri brojke i zašto baš one

- **Plafon troška** (`PLAFON_CENTI`) se proverava **pre** svakog poziva. Posle
  poziva se ne može poništiti trošak, pa plafon sme da bude prekoračen za najviše
  jedan poziv — a jedan poziv je ograničen veličinom brifa (200 KB, ADR-0041 §1).
  To se ovde kaže naglas umesto da se tvrdi tvrda granica koje nema (ADR-0033).
- **Najviše pokušaja** (`NAJVISE_POKUSAJA`) se broji po zakrpama koje je napisao
  model, ne po pozivima — jer se plaća ishod, a ne trud.
- **Prekidač „nema napretka"** staje pre plafona kad se pokušaj ponavlja: isti
  diff kao ranije, ili dve uzastopne izmerene zakrpe koje obaraju iste kapije.
  Agent koji stane sa „nisam uspeo" je ispravan ishod; agent koji melje nije.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from django.db import transaction

from apps.llm_gateway import gateway
from apps.orchestration import brif, zakrpa
from common import enums as E

from .models import CodeTask, GateResult, TaskPatch
from .zadaci import TaskError

__all__ = ["Ishod", "pokusaj", "potroseno", "izvuci_diff", "zasto_ne", "otisak",
           "PLAFON_CENTI", "NAJVISE_POKUSAJA"]

#: Plafon troška po zadatku, u EUR centima (Canon §13.1 — nikad float).
PLAFON_CENTI = 60

#: Koliko zakrpa model sme da napiše za jedan zadatak.
NAJVISE_POKUSAJA = 3

#: Koliko izlaza tražimo od modela. Diff od 20 KB je već prevelik za uzak
#: zadatak; preko toga se zadatak deli, ne podiže plafon (ADR-0041 §1).
MAX_DIFF_ZNAKOVA = 20_000

_OGRADA = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.S)
_POCETAK = re.compile(r"^diff --git ", re.M)

SISTEM = """Ti si programer u firmi Web Korporacija i radiš po pravilima koja se ne pregovaraju.

PRAVILO NULA: PRETPOSTAVKA JE MAJKA SVIH ZAJEBA. Ako nešto ne vidiš u priloženim
fajlovima, ne izmišljaj — reci da ti nedostaje i stani.

Ograničenja:
- Smeš da diraš ISKLJUČIVO putanje navedene u zadatku. Sve ostalo je van tvog posla.
- Zaštićene zone se ne diraju ni pod kojim izgovorom, ni preimenovanjem fajla.
- Ne praviš simboličke linkove i ne šalješ binarni sadržaj.
- Kod mora da prođe: pytest, ruff, canon_lint i `makemigrations --check`.

Odgovor: SAMO unified diff, u jednom bloku ograđenom sa ```diff.
Bez uvoda, bez objašnjenja posle, bez više blokova. Putanje pišeš kao
`a/putanja` i `b/putanja`. Nov fajl nosi `new file mode 100644` i `--- /dev/null`.

Ako zadatak ne možeš da uradiš u okviru datih putanja, odgovori jednim redom koji
počinje sa NE MOGU: i razlogom. To je ispravan ishod, ne neuspeh."""


@dataclass
class Ishod:
    """Šta je jedan pokušaj dao."""

    napisano: bool = False
    zakrpa_id: str = ""
    status: str = ""
    razlog: str = ""
    cena_centi: int = 0
    potroseno_ukupno: int = 0
    pokusaja: int = 0
    putanje: list[str] = field(default_factory=list)
    model: str = ""


# ------------------------------------------------------------------ računica


def _zakrpe_modela(zadatak: CodeTask):
    """Zakrpe nastale iz modela — one koje su nešto koštale ili ih je pisao pisac."""
    return zadatak.patches.order_by("created_at")


def potroseno(zadatak: CodeTask) -> int:
    """Koliko je model dosad koštao na ovom zadatku, u centima."""
    return sum(p.cost_eur_cents for p in zadatak.patches.all())


def _izmerene_pale(zadatak: CodeTask) -> list[tuple[str, ...]]:
    """Po zakrpi: koje su kapije pale. Samo izmerene zakrpe, hronološki."""
    ishodi: dict[str, dict[str, bool]] = {}
    redosled: list[str] = []
    for red in (GateResult.objects.filter(task=zadatak, patch__isnull=False)
                .order_by("created_at")
                .values_list("patch_id", "gate", "passed")):
        kljuc = str(red[0])
        if kljuc not in ishodi:
            ishodi[kljuc] = {}
            redosled.append(kljuc)
        ishodi[kljuc][red[1]] = red[2]
    return [tuple(sorted(g for g, ok in ishodi[k].items() if not ok)) for k in redosled]


def zasto_ne(zadatak: CodeTask, *, plafon_centi: int = PLAFON_CENTI,
             najvise: int = NAJVISE_POKUSAJA) -> str | None:
    """Razlog zašto se novi pokušaj NE pravi, ili `None` ako sme.

    Jedno mesto za sve prekidače — da se ne bi desilo da komanda proverava jedno,
    a servis drugo.
    """
    if zadatak.assignee_id is None:
        return "zadatak nema izvršioca"
    if zadatak.status in (E.TaskStatus.DONE.value, E.TaskStatus.CANCELLED.value):
        return f"zadatak je {zadatak.status}"

    nemereno = zadatak.patches.filter(status=E.PatchStatus.ACCEPTED.value,
                                      gates__isnull=True).exists()
    if nemereno:
        return ("već postoji prihvaćena a neizmerena zakrpa — poslušnik radi; "
                "novi pokušaj bi pisao preko tuđeg posla (ADR-0040)")

    broj = _zakrpe_modela(zadatak).count()
    if broj >= najvise:
        return f"dostignut plafon pokušaja ({broj}/{najvise})"

    trosak = potroseno(zadatak)
    if trosak >= plafon_centi:
        return f"potrošeno {trosak} od {plafon_centi} centi za ovaj zadatak"

    pale = _izmerene_pale(zadatak)
    if len(pale) >= 2 and pale[-1] and pale[-1] == pale[-2]:
        return ("nema napretka — dva puta zaredom padaju iste kapije: "
                + ", ".join(pale[-1]))

    if not [r for r in gateway.routes(E.LLMPurpose.CODE_PATCH, zadatak.assignee)
            if r.provider != gateway.LOCAL_PROVIDER]:
        return ("nema rute za pisanje koda — podesi je sa "
                "`manage.py llm_route add --purpose code_patch …` pa `enable`")
    return None


# --------------------------------------------------------------------- čitanje


def izvuci_diff(tekst: str) -> str | None:
    """Vadi unified diff iz odgovora modela, ili `None` ako ga nema.

    Model ume da doda uvod i zaključak ma šta pisalo u uputstvu. Uzima se prvi
    blok koji stvarno liči na diff; ako ograde nema, seče se od prvog
    `diff --git`. Ono što ne liči na diff se ne nagađa — vraća se `None`.
    """
    for telo in _OGRADA.findall(tekst or ""):
        if _POCETAK.search(telo):
            return telo.strip() + "\n"
    m = _POCETAK.search(tekst or "")
    if m:
        return (tekst[m.start():]).strip() + "\n"
    return None


def _prompt(zadatak: CodeTask) -> tuple[str, dict]:
    """Brif pretvoren u tekst za model. Ono što je odsečeno se KAŽE."""
    b = brif.build(zadatak)
    delovi = [
        f"ZADATAK {b['task_id']}: {b['title']}",
        f"ZAŠTO: {b['why']}",
        f"ADR: {b['adr'] or '—'}",
        "",
        "SMEŠ DA DIRAŠ SAMO: " + ", ".join(b["allowed_paths"]),
        "KAPIJE KOJE MORAJU DA PROĐU: " + ", ".join(b["required_gates"]),
        "ZAŠTIĆENE ZONE (nikada): " + ", ".join(b["protected_paths"]),
    ]
    if b["truncated"]:
        delovi += ["", "NISI DOBIO SVE — ovo je izostavljeno i zašto:"]
        delovi += [f"  · {t['path']}: {t['reason']}" for t in b["truncated"]]
    if b["failed_gates"]:
        delovi += ["", "PROŠLI PUT SU PALE OVE KAPIJE:"]
        for g in b["failed_gates"]:
            delovi.append(f"  · {g.get('gate')}: {str(g.get('detail', ''))[-1500:]}")
    if b["open_findings"]:
        delovi += ["", "OTVORENI NALAZI RECENZENTA:"]
        for n in b["open_findings"]:
            delovi.append(f"  · [{n.get('severity')}] {n.get('file')}:"
                          f"{n.get('line') or '-'} — {n.get('claim')}")
    delovi += ["", "FAJLOVI (trenutno stanje):"]
    for f in b["files"]:
        delovi += [f"--- {f['path']} ---", f["content"], ""]
    return "\n".join(delovi), b


# -------------------------------------------------------------------- pokušaj


@transaction.atomic
def _upisi(zadatak: CodeTask, diff: str | None, tekst: str, g, b: dict) -> TaskPatch:
    if diff is None:
        prvi = (tekst or "").strip().splitlines()[:1]
        razlog = ("model nije vratio diff: "
                  + (prvi[0][:300] if prvi else "prazan odgovor"))
        return zakrpa.zabelezi_neuspeh(zadatak, persona=zadatak.assignee, tekst=tekst,
                                       razlog=razlog, cena_centi=g.amount_eur_cents)
    if otisak(diff) in {otisak(p.diff) for p in zadatak.patches.all()}:
        # Isti pokušaj drugi put je novac bačen na krug u mestu. Beleži se kao
        # neuspeh, sa troškom — jer se poziv već platio (ADR-0044).
        return zakrpa.zabelezi_neuspeh(
            zadatak, persona=zadatak.assignee, tekst=diff,
            razlog="nema napretka — ista zakrpa je već predata na ovom zadatku",
            cena_centi=g.amount_eur_cents)
    if len(diff) > MAX_DIFF_ZNAKOVA:
        return zakrpa.zabelezi_neuspeh(
            zadatak, persona=zadatak.assignee, tekst=diff,
            razlog=f"diff je {len(diff)} znakova — preko {MAX_DIFF_ZNAKOVA}; "
                   "podeli zadatak (ADR-0041 §1)",
            cena_centi=g.amount_eur_cents)
    return zakrpa.submit(zadatak, diff, persona=zadatak.assignee,
                         cena_centi=g.amount_eur_cents)


def pokusaj(zadatak: CodeTask, *, plafon_centi: int = PLAFON_CENTI,
            najvise: int = NAJVISE_POKUSAJA) -> Ishod:
    """Jedan pokušaj: brif → model → zakrpa. Ne vrti kapije i ne zatvara zadatak."""
    kocnica = zasto_ne(zadatak, plafon_centi=plafon_centi, najvise=najvise)
    if kocnica:
        return Ishod(razlog=kocnica, potroseno_ukupno=potroseno(zadatak),
                     pokusaja=_zakrpe_modela(zadatak).count())

    tekst_prompta, b = _prompt(zadatak)
    try:
        g = gateway.generate(E.LLMPurpose.CODE_PATCH, SISTEM, tekst_prompta,
                             persona=zadatak.assignee)
    except gateway.LLMError as e:
        raise TaskError("NO_MODEL", f"Model nije odgovorio: {e}") from e

    if g.provider == gateway.LOCAL_PROVIDER:
        # Lokalni šablon ume da napiše rečenicu, ne zakrpu. Da mu pustimo odgovor
        # kao pokušaj, brojali bismo kao neuspeh agenta nešto što nije ni model.
        raise TaskError(
            "LOCAL_ONLY",
            "Zahtev je pao na lokalni šablon, a on ne piše kod. Uključi rutu za "
            "`code_patch` i LLM_EXTERNAL_ENABLED (ADR-0009).")

    diff = izvuci_diff(g.text)
    red = _upisi(zadatak, diff, g.text, g, b)
    return Ishod(
        napisano=red.status == E.PatchStatus.ACCEPTED.value,
        zakrpa_id=str(red.pk), status=red.status, razlog=red.reason,
        cena_centi=red.cost_eur_cents, potroseno_ukupno=potroseno(zadatak),
        pokusaja=_zakrpe_modela(zadatak).count(), putanje=list(red.paths),
        model=f"{g.provider}/{g.model}",
    )


def otisak(diff: str) -> str:
    """Otisak zakrpe — da se isti pokušaj prepozna i kad je tekst prepisan."""
    return hashlib.sha256(" ".join((diff or "").split()).encode()).hexdigest()[:16]
