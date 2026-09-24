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
    "finish",
    "gate_report",
]


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

    zadatak = CodeTask.objects.create(
        public_id=ulid_public_id(EntityKind.CODE_TASK),
        title=title.strip(), why=why.strip(), adr=adr.strip(),
        allowed_paths=putanje, required_gates=kapije,
        requested_by=requested_by, assignee=assignee, reviewer=reviewer,
        plan=plan, run=run,
        status=E.TaskStatus.ASSIGNED if assignee else E.TaskStatus.DRAFT,
    )
    audit.record("task.created", persona=assignee or requested_by, details={
        "task": zadatak.public_id, "title": zadatak.title, "adr": zadatak.adr,
        "allowed_paths": putanje, "required_gates": kapije,
        "assignee": getattr(assignee, "public_id", None),
        "reviewer": getattr(reviewer, "public_id", None),
    })
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


def may_touch(zadatak: CodeTask, path: str, *, persona: Persona | None = None,
              capability: str = "code.write") -> str | None:
    """Vraća razlog zašto se putanja NE sme dirati, ili `None` ako sme.

    Razlog je tekst namenjen čoveku i auditu; poziva se pre svake izmene fajla.
    """
    p = policy.normalize_path(path)
    zona = policy.path_is_protected(p)
    if zona:
        return f"zaštićena zona ({zona})"
    if not any(p == d.rstrip("/") or p.startswith(d.rstrip("/") + "/")
               for d in zadatak.allowed_paths):
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
                commit_sha: str = "") -> GateResult:
    """Upisuje jedan pokušaj jedne kapije. Svaki pokušaj ostaje — i pali."""
    g = E.Gate(gate).value if gate in E.Gate.values() else None
    if g is None:
        raise TaskError("UNKNOWN_GATE", f"Nepoznata kapija {gate!r}.")
    red = GateResult.objects.create(
        task=zadatak, gate=g, passed=bool(passed), detail=detail[:4000],
        commit_sha=commit_sha,
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
    """Nalaz recenzenta. Autor ne recenzira sopstveni rad."""
    if reviewer and zadatak.assignee_id and reviewer.pk == zadatak.assignee_id:
        raise TaskError("SELF_REVIEW", "Autor ne piše nalaz na sopstveni rad "
                                       "(ADR-0034 §5.2).")
    if severity not in E.FindingSeverity.values():
        raise TaskError("UNKNOWN_SEVERITY", f"Nepoznata težina {severity!r}.")
    if not claim.strip():
        raise TaskError("EMPTY_CLAIM", "Nalaz bez tvrdnje nije nalaz.")

    nalaz = ReviewFinding.objects.create(
        task=zadatak, reviewer=reviewer, file=policy.normalize_path(file),
        line=line, claim=claim.strip(), severity=severity, source=source,
    )
    audit.record("task.finding.added", persona=reviewer, details={
        "task": zadatak.public_id, "file": nalaz.file, "line": line,
        "severity": severity, "source": source,
    })
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
