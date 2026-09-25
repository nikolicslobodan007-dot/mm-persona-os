"""Rezultat zadatka ide u granu, nikad u `main`. ADR-0043.

Do sada je posao agenta nestajao. Poslušnik napravi radni primerak, primeni
zakrpu, izvrti kapije — i obriše sve. Ostane zapis da je bilo zeleno i nijedan
red koda koji bi čovek mogao da pogleda. Merenje bez proizvoda.

Ovaj modul daje proizvod: **commit na grani `zadatak/TSK-…`**, sa agentom kao
autorom i sistemom kao pošiljaocem. `main` i dalje menja isključivo ljudska ruka
(ADR-0038 §6); ovde se samo sprema ono što će ta ruka pogledati.

Tri pravila:

  - **Ime grane i poruka commita prave se ovde, ne u poslušniku.** Poslušnik ne
    sastavlja tekst — dobije gotov i proveri mu oblik. Tako agentov naslov nikad
    ne postaje argument komandne linije.
  - **Grana se pomera samo sa mesta koje aplikacija zna.** Poslušnik gura sa
    `--force-with-lease` na `commit_sha` koji je zapisan ovde. Ako se grana na
    disku razlikuje, guranje pada — neko ju je dirao rukom, a to je tačno trenutak
    kada mašina treba da stane.
  - **Zapisuje se tek kad su kapije zelene NAD TOM zakrpom.** Zelena kapija nad
    starijom zakrpom ne otvara granu novoj (ADR-0040).
"""

from __future__ import annotations

import re
import unicodedata

from django.db import transaction

from api import audit
from apps.personas.models import Persona
from common import enums as E

from .models import CodeTask, GateResult, TaskPatch
from .zadaci import TaskError, blocking_findings

__all__ = [
    "DOMEN_AGENATA",
    "POSILJALAC",
    "PREFIKS_GRANE",
    "ime_grane",
    "potpis",
    "poruka",
    "priprema",
    "zabelezi",
    "za_pregled",
]

#: Poddomen sa kog agenti „potpisuju" commit. Adresa je jedinstvena po agentu da
#: bi `git log --author` radio, i namerno ne prima poštu — poddomen nema MX zapis
#: i ne sme ga dobiti. Adresa je oznaka, ne sanduče.
DOMEN_AGENATA = "agenti.webkorporacija.com"

#: Pošiljalac (`committer`) je uvek sistem, ma ko bio autor. Ko je napisao i ko je
#: pustio su dva različita pitanja i git ih ume razlikovati — koristimo to.
POSILJALAC: tuple[str, str] = ("MM Persona OS", f"poslusnik@{DOMEN_AGENATA}")

PREFIKS_GRANE = "zadatak/"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_TSK = re.compile(r"^TSK-[0-9A-HJKMNP-TV-Z]{26}$")
_MAX_NASLOV = 64


def _bez_upravljackih(tekst: str, *, koliko: int = 200) -> str:
    """Skida sve što bi u `git` zaglavlju značilo nešto drugo nego tekst.

    Prelom reda deli zaglavlje od tela, a `<` i `>` ograđuju adresu. Naslov
    zadatka piše agent; ako prođe kako jeste, agent sam sebi bira ime autora.
    """
    ociscen = "".join(
        " " if unicodedata.category(z)[0] == "C" or z in "<>" else z
        for z in (tekst or "")
    )
    return " ".join(ociscen.split())[:koliko].strip()


def ime_grane(zadatak: CodeTask) -> str:
    """`zadatak/TSK-…` — jedna grana po zadatku, izvedena iz identifikatora.

    Ime se ne čuva u bazi jer nema šta da se čuva: izvedeno je, pa ne može da se
    razmimoiđe sa zadatkom.
    """
    if not _TSK.match(zadatak.public_id or ""):
        raise TaskError("BAD_TASK_ID", f"Neispravan identifikator {zadatak.public_id!r}.")
    return f"{PREFIKS_GRANE}{zadatak.public_id}"


def potpis(persona: Persona | None) -> tuple[str, str]:
    """Ime i adresa autora commita. Bez izvršioca nema potpisa — ni commita."""
    if persona is None:
        raise TaskError("NO_AUTHOR", "Zadatak nema izvršioca, pa commit nema autora.")
    ime = _bez_upravljackih(persona.display_name, koliko=80) or persona.public_id
    return ime, f"{persona.public_id.lower()}@{DOMEN_AGENATA}"


def poruka(zadatak: CodeTask, zakrpa: TaskPatch) -> str:
    """Poruka commita. Sastavlja je aplikacija, da je poslušnik ne bi sastavljao.

    Nosi ono što se posle godinu dana ne može rekonstruisati ni iz čega drugog:
    ko je agent, koji zadatak, koja zakrpa, nad kojom osnovom, po kom ADR-u.
    """
    naslov = _bez_upravljackih(zadatak.title, koliko=_MAX_NASLOV) or "bez naslova"
    ime, mejl = potpis(zadatak.assignee)
    redovi = [
        f"{zadatak.public_id}: {naslov}",
        "",
        _bez_upravljackih(zadatak.why, koliko=600) or "(bez obrazloženja)",
        "",
        f"Zakrpa: {zakrpa.pk}",
        f"Osnova: {zakrpa.base_sha or '(nepoznata)'}",
        f"Putanje: {', '.join(zadatak.allowed_paths)}",
        "",
        f"Persona: {zadatak.assignee.public_id} ({ime} <{mejl}>)",
    ]
    if zadatak.adr:
        redovi.append(f"ADR: {_bez_upravljackih(zadatak.adr, koliko=80)}")
    redovi += [
        "",
        "Napisao agent MM Persona OS. Kapije su prošle nad ovom zakrpom; u `main`",
        "ulazi isključivo ljudskom rukom (ADR-0038 §6, ADR-0043).",
    ]
    return "\n".join(redovi) + "\n"


def _kapije_zakrpe(zadatak: CodeTask, zakrpa: TaskPatch) -> dict[str, bool | None]:
    """Poslednji ishod po traženoj kapiji **nad ovom zakrpom**.

    `zadaci.gate_report` gleda zadatak u celini; to je tačno za čoveka, a pogrešno
    za granu: zelena kapija nad prošlom zakrpom ne govori ništa o ovoj.
    """
    ishod: dict[str, bool | None] = {g: None for g in zadatak.required_gates}
    for red in GateResult.objects.filter(task=zadatak, patch=zakrpa).order_by("created_at"):
        if red.gate in ishod:
            ishod[red.gate] = red.passed
    return ishod


def priprema(zadatak: CodeTask, zakrpa: TaskPatch) -> dict:
    """Sve što poslušniku treba da napravi commit — i ništa čemu bi morao da veruje."""
    ime, mejl = potpis(zadatak.assignee)
    return {
        "branch": ime_grane(zadatak),
        # Sa čim aplikacija očekuje da se grana na disku poklapa. Prazno znači
        # „grane još nema"; tada guranje sme samo ako je zaista nema.
        "branch_expected_sha": zadatak.commit_sha or "",
        "author_name": ime,
        "author_email": mejl,
        "committer_name": POSILJALAC[0],
        "committer_email": POSILJALAC[1],
        "commit_message": poruka(zadatak, zakrpa),
    }


@transaction.atomic
def zabelezi(zadatak: CodeTask, zakrpa: TaskPatch, *, branch: str,
             commit_sha: str) -> TaskPatch:
    """Upisuje granu i commit kao rezultat ove zakrpe. Ne zatvara zadatak.

    Zatvaranje ostaje `zadaci.finish` i ljudska ruka: grana je ponuda na sto, a ne
    odluka (ADR-0038 §6).
    """
    if zakrpa.task_id != zadatak.pk:
        raise TaskError("WRONG_TASK", "Zakrpa ne pripada ovom zadatku.")
    if zakrpa.status not in (E.PatchStatus.ACCEPTED.value, E.PatchStatus.APPLIED.value):
        raise TaskError("PATCH_NOT_ACCEPTED",
                        f"Zakrpa je {zakrpa.status}; u granu ide samo prihvaćena.")

    sha = (commit_sha or "").strip().lower()
    if not _SHA.match(sha):
        raise TaskError("BAD_SHA", "Commit mora biti 40 heksadecimalnih cifara.")
    ocekivana = ime_grane(zadatak)
    if branch != ocekivana:
        raise TaskError("BAD_BRANCH",
                        f"Grana mora biti {ocekivana!r}, stigla {branch!r}.")

    ishod = _kapije_zakrpe(zadatak, zakrpa)
    pale = [g for g, ok in ishod.items() if ok is not True]
    if pale:
        raise TaskError(
            "GATES_NOT_GREEN",
            "Grana se ne otvara: " + ", ".join(
                f"{g} ({'nije vrtena nad ovom zakrpom' if ishod[g] is None else 'pala'})"
                for g in pale),
            {"gates": pale},
        )
    blokade = list(blocking_findings(zadatak).values_list("file", "line"))
    if blokade:
        raise TaskError("OPEN_BLOCKERS",
                        "Otvoren nalaz težine BLOCKER: " + ", ".join(
                            f"{f}:{ln or '-'}" for f, ln in blokade))

    if zakrpa.applied_sha and zakrpa.applied_sha != sha:
        raise TaskError(
            "RESULT_CONFLICT",
            f"Zakrpa već ima commit {zakrpa.applied_sha}; drugi ({sha}) se ne upisuje "
            f"preko njega.", {"applied_sha": zakrpa.applied_sha},
        )

    ponovljeno = zakrpa.applied_sha == sha
    zakrpa.applied_sha = sha
    zakrpa.status = E.PatchStatus.APPLIED
    zakrpa.save(update_fields=["applied_sha", "status", "updated_at"])
    zadatak.commit_sha = sha
    zadatak.save(update_fields=["commit_sha", "updated_at"])

    audit.record("task.result.branched", persona=zadatak.assignee, details={
        "task": zadatak.public_id, "patch": str(zakrpa.pk), "branch": branch,
        "commit": sha, "repeat": ponovljeno,
    })
    return zakrpa


def za_pregled() -> list[dict]:
    """Zadaci koji imaju granu sa commitom, a još nisu zatvoreni ljudskom rukom."""
    redovi = []
    for zadatak in (CodeTask.objects.exclude(commit_sha="")
                    .exclude(status__in=[E.TaskStatus.DONE.value,
                                         E.TaskStatus.CANCELLED.value])
                    .order_by("created_at")):
        zakrpa = (zadatak.patches.filter(applied_sha=zadatak.commit_sha)
                  .order_by("-created_at").first())
        redovi.append({
            "task": zadatak.public_id,
            "title": zadatak.title,
            "branch": ime_grane(zadatak),
            "commit": zadatak.commit_sha,
            "agent": getattr(zadatak.assignee, "public_id", "—"),
            "ime": getattr(zadatak.assignee, "display_name", ""),
            "gates": _kapije_zakrpe(zadatak, zakrpa) if zakrpa else {},
            "blokera": blocking_findings(zadatak).count(),
        })
    return redovi
