"""Zadaci programerskog sektora. ADR-0034 §3, ADR-0035.

Modul se zove `zadaci`, a ne `tasks`, jer Celery autodiscovery uzima `tasks.py`
iz svakog app-a — ime bi bilo tiha zamka.

Tri provere pre svakog dodira fajla, i sve tri moraju da prođu (ADR-0035 §2):

    1. putanja nije zaštićena zona     — tvrdo, ne otvara se ni zadatkom ni nivoom
    2. putanja je pod dozvoljenim prefiksom ovog zadatka
    3. poverenje agenta za `code.write` na toj putanji je bar `L1`

Gotovo nije tvrdnja nego merenje: `finish()` odbija dok svaka tražena kapija nema
zelen zapis i dok ima otvorenog nalaza težine `BLOCKER`.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from api import audit
from apps.personas.models import Persona
from apps.policy import service as policy
from common import enums as E
from common.ids import EntityKind, ulid_public_id

from .models import CodeTask, GateResult, ReviewFinding

__all__ = [
    "TaskError",
    "create",
    "assign",
    "may_touch",
    "record_gate",
    "add_finding",
    "amend_finding",
    "close_finding",
    "finish",
    "gate_report",
    "IZVOR_COVEK",
]

#: Izvor nalaza koji je napisao čovek. Jedini izvor kome je dozvoljen `BLOCKER`
#: (ADR-0036 §2, sprovedeno od ADR-0045). Mašinski izvori nose ime alata.
IZVOR_COVEK = "covek"


class TaskError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.details = code, details or {}


# ------------------------------------------------------------------ pravljenje


def _clean_paths(paths) -> list[str]:
    """Normalizuje, odbacuje prazno i duplikate, čuva redosled."""
    out: list[str] = []
    for raw in paths or []:
        p = policy.normalize_path(raw)
        if p and p not in out:
            out.append(p)
    return out


def _clean_gates(gates) -> list[str]:
    poznate = set(E.Gate.values())
    out: list[str] = []
    for g in gates if gates is not None else E.DEFAULT_GATES:
        g = str(g).strip()
        if g not in poznate:
            raise TaskError("UNKNOWN_GATE", f"Nepoznata kapija {g!r}; poznate: "
                                            f"{sorted(poznate)}")
        if g not in out:
            out.append(g)
    return out


@transaction.atomic
def create(*, title: str, why: str, allowed_paths, adr: str = "",
           gates=None, requested_by: Persona | None = None,
           assignee: Persona | None = None, reviewer: Persona | None = None,
           plan=None, run=None) -> CodeTask:
    """Pravi zadatak. Odbija prazan spisak putanja i zaštićenu zonu u njemu."""
    if not title.strip():
        raise TaskError("NO_TITLE", "Zadatak bez naslova.")
    if not why.strip():
        raise TaskError("NO_REASON", "Zadatak bez razloga — zašto se radi (ADR-0034 §4).")

    putanje = _clean_paths(allowed_paths)
    if not putanje:
        raise TaskError(
            "NO_PATHS",
            "Zadatak mora da navede bar jednu dozvoljenu putanju. Prazan spisak "
            "znači „svuda”, a to nije zadatak nego opis posla (ADR-0035 §1).",
        )
    for p in putanje:
        zona = policy.path_is_protected(p)
        if zona:
            raise TaskError(
                "PROTECTED_PATH",
                f"{p} je u zaštićenoj zoni ({zona}) — nijedan zadatak je ne otvara "
                f"(ADR-0034 §5.1).", {"path": p, "zone": zona},
            )

    kapije = _clean_gates(gates)
    if assignee and reviewer and assignee.pk == reviewer.pk:
        raise TaskError("SELF_REVIEW", "Recenzent ne sme biti autor (ADR-0034 §5.2).")

    # Izvršilac se NE upisuje ovde. Dodela ima svoju proveru poverenja, a da je
    # `create` zaobilazi, cela provera iz ADR-0035 §2 bi se gasila time što se
    # izvršilac prosledi pri pravljenju umesto posle. Jedan put, ne dva.
    zadatak = CodeTask.objects.create(
        public_id=ulid_public_id(EntityKind.CODE_TASK),
        title=title.strip(), why=why.strip(), adr=adr.strip(),
        allowed_paths=putanje, required_gates=kapije,
        requested_by=requested_by, reviewer=reviewer, plan=plan, run=run,
        status=E.TaskStatus.DRAFT,
    )
    audit.record("task.created", persona=assignee or requested_by, details={
        "task": zadatak.public_id, "title": zadatak.title, "adr": zadatak.adr,
        "allowed_paths": putanje, "required_gates": kapije,
        "assignee": getattr(assignee, "public_id", None),
        "reviewer": getattr(reviewer, "public_id", None),
    })
    if assignee:
        assign(zadatak, assignee=assignee, reviewer=reviewer)
    return zadatak


@transaction.atomic
def assign(zadatak: CodeTask, *, assignee: Persona, reviewer: Persona | None = None,
           capability: str = "code.write") -> CodeTask:
    """Dodeljuje zadatak — i proverava da agent uopšte sme na te putanje.

    Provera je po svakoj dozvoljenoj putanji posebno: agent sa `L1` u
    `apps/content` i `L0` u `apps/channels` ne dobija zadatak koji dira oba.
    """
    recenzent = reviewer if reviewer is not None else zadatak.reviewer
    if recenzent and recenzent.pk == assignee.pk:
        raise TaskError("SELF_REVIEW", "Recenzent ne sme biti autor (ADR-0034 §5.2).")

    manjak = [
        p for p in zadatak.allowed_paths
        if not policy.config.trust_at_least(
            policy.trust_for(assignee, capability, p), E.TrustLevel.L1)
    ]
    if manjak:
        raise TaskError(
            "TRUST_TOO_LOW",
            f"{assignee.public_id} nema {capability} ≥ L1 na: {', '.join(manjak)}.",
            {"paths": manjak, "capability": capability},
        )

    zadatak.assignee = assignee
    zadatak.reviewer = recenzent
    zadatak.status = E.TaskStatus.ASSIGNED
    zadatak.save(update_fields=["assignee", "reviewer", "status", "updated_at"])
    audit.record("task.assigned", persona=assignee, details={
        "task": zadatak.public_id, "assignee": assignee.public_id,
        "reviewer": getattr(recenzent, "public_id", None), "capability": capability,
    })
    return zadatak


# --------------------------------------------------------------------- granica


def under_any(path: str, prefixes) -> bool:
    """Da li je putanja pod nekim od prefiksa. Jedno mesto, jer se pravilo
    poklapanja postavlja i pri izmeni fajla i pri uvozu recenzije."""
    p = policy.normalize_path(path)
    return any(p == d.rstrip("/") or p.startswith(d.rstrip("/") + "/")
               for d in prefixes)


def may_touch(zadatak: CodeTask, path: str, *, persona: Persona | None = None,
              capability: str = "code.write") -> str | None:
    """Vraća razlog zašto se putanja NE sme dirati, ili `None` ako sme.

    Razlog je tekst namenjen čoveku i auditu; poziva se pre svake izmene fajla.
    """
    p = policy.normalize_path(path)
    zona = policy.path_is_protected(p)
    if zona:
        return f"zaštićena zona ({zona})"
    if not under_any(p, zadatak.allowed_paths):
        return "van dozvoljenih putanja ovog zadatka"
    agent = persona or zadatak.assignee
    if agent is None:
        return "zadatak nema izvršioca"
    nivo = policy.trust_for(agent, capability, p)
    if not policy.config.trust_at_least(nivo, E.TrustLevel.L1):
        return f"poverenje {nivo.value} za {capability} na toj putanji"
    return None


# ---------------------------------------------------------------------- kapije


@transaction.atomic
def record_gate(zadatak: CodeTask, gate: str, passed: bool, *, detail: str = "",
                commit_sha: str = "", patch=None) -> GateResult:
    """Upisuje jedan pokušaj jedne kapije. Svaki pokušaj ostaje — i pali."""
    g = E.Gate(gate).value if gate in E.Gate.values() else None
    if g is None:
        raise TaskError("UNKNOWN_GATE", f"Nepoznata kapija {gate!r}.")
    red = GateResult.objects.create(
        task=zadatak, gate=g, passed=bool(passed), detail=detail[:4000],
        commit_sha=commit_sha, patch=patch,
    )
    audit.record(
        "task.gate.recorded",
        severity=E.AuditSeverity.INFO if passed else E.AuditSeverity.WARNING,
        persona=zadatak.assignee,
        details={"task": zadatak.public_id, "gate": g, "passed": bool(passed),
                 "commit": commit_sha},
    )
    return red


def gate_report(zadatak: CodeTask) -> dict[str, bool | None]:
    """Poslednji ishod po traženoj kapiji: `True`, `False` ili `None` (nije vrtena)."""
    ishod: dict[str, bool | None] = {g: None for g in zadatak.required_gates}
    for red in zadatak.gates.order_by("created_at"):
        if red.gate in ishod:
            ishod[red.gate] = red.passed
    return ishod


def blocking_findings(zadatak: CodeTask):
    return zadatak.findings.filter(
        severity=E.FindingSeverity.BLOCKER.value, status=E.FindingStatus.OPEN.value
    )


# --------------------------------------------------------------------- nalazi


@transaction.atomic
def add_finding(zadatak: CodeTask, *, reviewer: Persona | None, file: str,
                claim: str, severity: str, line: int | None = None,
                source: str = "agent") -> ReviewFinding:
    """Nalaz recenzenta. Autor ne recenzira sopstveni rad.

    `BLOCKER` sme da postavi **samo čovek** (ADR-0036 §2). Do ADR-0045 je to
    pravilo živelo jedino kao tabela preslikavanja u uvozniku SARIF-a — dakle
    kao nešto što se može zaobići time što se doda drugi put do ove funkcije.
    Pravilo koje je moguće zaobići nije pravilo, pa sada stoji ovde.
    """
    if reviewer and zadatak.assignee_id and reviewer.pk == zadatak.assignee_id:
        raise TaskError("SELF_REVIEW", "Autor ne piše nalaz na sopstveni rad "
                                       "(ADR-0034 §5.2).")
    if severity not in E.FindingSeverity.values():
        raise TaskError("UNKNOWN_SEVERITY", f"Nepoznata težina {severity!r}.")
    if not claim.strip():
        raise TaskError("EMPTY_CLAIM", "Nalaz bez tvrdnje nije nalaz.")
    if severity == E.FindingSeverity.BLOCKER.value and source != IZVOR_COVEK:
        raise TaskError(
            "MACHINE_BLOCKER",
            f"`BLOCKER` postavlja samo čovek; izvor {source!r} ne sme "
            f"(ADR-0036 §2).", {"source": source},
        )

    nalaz = ReviewFinding.objects.create(
        task=zadatak, reviewer=reviewer, file=policy.normalize_path(file),
        line=line, claim=claim.strip(), severity=severity, source=source,
    )
    audit.record("task.finding.added", persona=reviewer, details={
        "task": zadatak.public_id, "file": nalaz.file, "line": line,
        "severity": severity, "source": source,
    })
    return nalaz


@transaction.atomic
def amend_finding(nalaz: ReviewFinding, claim: str, *, actor: str = "") -> ReviewFinding:
    """Ispravlja **tvrdnju** nalaza. Težina i status se ovuda ne diraju.

    Greška u kucanju ne sme da tera na lažno zatvaranje nalaza — a dupliranje
    nalaza zbog pravopisa kvari meru, jer `ucinak` broji nalaze po agentu.

    Tri granice, i sve tri su o tome da ispravka ne postane prepravljanje:

      - **samo otvoren nalaz.** Zatvoren je presuđen; njegov tekst je deo te
        presude i ne menja se naknadno;
      - **težina se ne menja.** Naknadno podizanje na `BLOCKER` je nova odluka o
        tuđem radu, a ne ispravka — to ide kao nov nalaz;
      - **izvršilac ne dira nalaz na sopstveni rad**, isto kao kod zatvaranja.

    Stara tvrdnja ostaje u auditu, pa se ispravka vidi.
    """
    if not claim.strip():
        raise TaskError("EMPTY_CLAIM", "Nalaz bez tvrdnje nije nalaz.")
    if nalaz.status != E.FindingStatus.OPEN.value:
        raise TaskError(
            "CLOSED_FINDING",
            f"Nalaz je {nalaz.status}; presuđen nalaz se ne prepravlja. Ako je "
            f"presuda pogrešna, ide nov nalaz.",
        )
    izvrsilac = getattr(nalaz.task.assignee, "public_id", None)
    if izvrsilac and actor == f"agent:{izvrsilac}":
        raise TaskError(
            "SELF_AMEND",
            f"{izvrsilac} ne dira nalaz na sopstveni rad (ADR-0034 §5.2).",
        )

    pre = nalaz.claim
    nalaz.claim = claim.strip()
    nalaz.save(update_fields=["claim", "updated_at"])
    audit.record("task.finding.amended", persona=nalaz.task.assignee, details={
        "task": nalaz.task.public_id, "finding": str(nalaz.pk),
        "file": nalaz.file, "severity": nalaz.severity,
        "pre": pre[:1000], "posle": nalaz.claim[:1000],
    })
    return nalaz


@transaction.atomic
def close_finding(nalaz: ReviewFinding, status: str, *, actor: str = "",
                  note: str = "") -> ReviewFinding:
    """Zatvara nalaz. Izvršilac ne zatvara nalaz na sopstveni rad.

    Kad bi smeo, `BLOCKER` bi bio ukras: agent koji ne sme da odobri svoj kod
    (ADR-0034 §5.2) ne sme ni da skloni prigovor na njega. Proverava se
    `actor`, jer se ovuda ne prolazi kao persona nego kao pozivalac.
    """
    if status not in E.FindingStatus.values():
        raise TaskError("UNKNOWN_STATUS", f"Nepoznat status {status!r}; poznati: "
                                          f"{sorted(E.FindingStatus.values())}")
    if status == E.FindingStatus.OPEN.value:
        raise TaskError("NOT_A_CLOSE", "`OPEN` nije zatvaranje.")

    izvrsilac = getattr(nalaz.task.assignee, "public_id", None)
    if izvrsilac and actor == f"agent:{izvrsilac}":
        raise TaskError(
            "SELF_CLOSE",
            f"{izvrsilac} ne zatvara nalaz na sopstveni rad (ADR-0034 §5.2).",
        )

    pre = nalaz.status
    nalaz.status = status
    nalaz.save(update_fields=["status", "updated_at"])
    audit.record("task.finding.closed",
                 severity=E.AuditSeverity.WARNING
                 if nalaz.severity == E.FindingSeverity.BLOCKER.value
                 else E.AuditSeverity.INFO,
                 persona=nalaz.task.assignee,
                 details={"task": nalaz.task.public_id, "finding": str(nalaz.pk),
                          "file": nalaz.file, "severity": nalaz.severity,
                          "iz": pre, "u": status, "note": note[:500]})
    return nalaz


# -------------------------------------------------------------------- zatvaranje


@transaction.atomic
def finish(zadatak: CodeTask, *, commit_sha: str = "") -> CodeTask:
    """Zatvara zadatak — ako kapije to dozvole. Pravilo nula (ADR-0033)."""
    izvestaj = gate_report(zadatak)
    pale = [g for g, ok in izvestaj.items() if ok is not True]
    if pale:
        raise TaskError(
            "GATES_NOT_GREEN",
            "Zadatak nije gotov: " + ", ".join(
                f"{g} ({'nije vrtena' if izvestaj[g] is None else 'pala'})"
                for g in pale),
            {"gates": pale},
        )
    blokade = list(blocking_findings(zadatak).values_list("file", "line"))
    if blokade:
        raise TaskError(
            "OPEN_BLOCKERS",
            "Otvoren nalaz težine BLOCKER: " + ", ".join(
                f"{f}:{ln or '-'}" for f, ln in blokade),
            {"findings": [f"{f}:{ln or '-'}" for f, ln in blokade]},
        )

    zadatak.status = E.TaskStatus.DONE
    zadatak.commit_sha = commit_sha or zadatak.commit_sha
    zadatak.finished_at = timezone.now()
    zadatak.save(update_fields=["status", "commit_sha", "finished_at", "updated_at"])
    audit.record("task.finished", persona=zadatak.assignee, details={
        "task": zadatak.public_id, "commit": zadatak.commit_sha,
        "gates": list(izvestaj),
    })
    return zadatak
