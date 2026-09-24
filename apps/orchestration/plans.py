"""Plan sa checkpointima — zadatak koji preživljava pauzu. ADR-0021.

Do sada je posao agenta bio jedan potez: buđenje → nacrt → akcija. Kad akcija
stane na odobrenje, priča se tu završava; ako je odbiješ, ne nastavlja se
ništa i niko ne zna da je zadatak ostao nedovršen.

Ovde zadatak postaje **plan sa koracima**:

    korak 1 → korak 2 (čeka odobrenje) ⏸ … odluka … ▶ korak 3 → gotovo

Tri pravila:

  - **Stanje je u bazi, ne u memoriji procesa.** `AgentPlan` + `PlanStep`
    postoje od F1; ovde se dodaje motor. Restart ne gubi ništa.
  - **Korak koji traži odobrenje pauzira plan**, a odluka ga nastavlja
    (`APPROVED`) ili zaustavlja (`REJECTED`) — sa zapisanim razlogom.
  - **Zadatak se završava na tri načina**, nikad tiho: `COMPLETED`,
    `ABANDONED` (sa razlogom) ili `EXPIRED`. Obrazac preuzet iz OpenHuman
    (Completed / AwaitingUser / Incomplete) — vidi beleške od 24.09.

Korak ne zna kako se izvršava akcija; on vraća jedan od tri ishoda i motor
odlučuje šta dalje. Tako isti plan radi i za poštu i za objavu i za sve što
dođe kasnije.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from api import audit
from apps.orchestration.models import Action, AgentPlan, PlanStep
from common import enums as E
from common import ids as I

PS, SS = E.PlanStatus, E.StepStatus
#: Koliko koraka sme jedan plan — zaštita od plana koji sam sebe produžava.
MAX_STEPS = 24
#: Koliko koraka motor izvrši u jednom prolazu, pre nego što stane.
MAX_PER_PASS = 12
#: Koliko duboko sme lanac „šef → izvršilac → njegov izvršilac" (ADR-0022).
MAX_DELEGATION_DEPTH = 3


class PlanError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- ishodi koraka


@dataclass(frozen=True)
class Done:
    """Korak je završen; plan ide dalje."""

    output: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Waiting:
    """Korak čeka čoveka. Plan se pauzira na ovom mestu i čuva stanje."""

    action: Action
    note: str = ""


@dataclass(frozen=True)
class Delegated:
    """Korak je predat drugom agentu. Čeka se njegov plan (ADR-0022)."""

    plan: AgentPlan
    note: str = ""


@dataclass(frozen=True)
class Failed:
    """Korak ne može da se završi. Plan staje, razlog se zapisuje."""

    reason: str


Outcome = Done | Waiting | Delegated | Failed
Handler = Callable[[PlanStep, dict], Outcome]
_HANDLERS: dict[str, Handler] = {}

#: Moduli koji registruju obrađivače. Motor ih učitava sam — obrađivač postoji
#: tek kad se njegov modul uveze, pa bi inače isti plan radio u jednom procesu
#: (worker koji je poštu primio), a padao u drugom (web koji nastavlja posle
#: odobrenja). Nalaz od 24.09.
HANDLER_MODULES = ("apps.channels.reply", "apps.content.steps")


def load_handlers() -> None:
    """Uvozi module sa obrađivačima. Uvoz je keširan, pa se ponavlja besplatno."""
    import importlib

    for name in HANDLER_MODULES:
        importlib.import_module(name)


def handler(name: str) -> Callable[[Handler], Handler]:
    """Registruje obrađivač koraka. `input_json["handler"]` bira koji se zove."""

    def wrap(fn: Handler) -> Handler:
        _HANDLERS[name] = fn
        return fn

    return wrap


def registered() -> list[str]:
    load_handlers()
    return sorted(_HANDLERS)


# ---------------------------------------------------------------- stanje plana


def state(plan: AgentPlan) -> dict:
    """Radno stanje celog plana, kao jedan rečnik.

    Izlazi koraka se **sabiraju**, ne prepisuju: korak vidi sve što su
    prethodni proizveli, po svom rednom broju i po imenu obrađivača.
    """
    out: dict = {"goal": plan.goal, "plan": plan.public_id, "steps": {}, "by_handler": {}}
    for s in plan.steps.order_by("sequence"):
        out["steps"][str(s.sequence)] = {"status": s.status, **(s.output_json or {})}
        name = (s.input_json or {}).get("handler", "")
        if name and s.output_json:
            out["by_handler"].setdefault(name, []).append(s.output_json)
    return out


def summary(plan: AgentPlan) -> str:
    steps = list(plan.steps.order_by("sequence"))
    done = sum(1 for s in steps if s.status == SS.DONE.value)
    return f"{plan.goal[:60]} — {done}/{len(steps)} koraka, {plan.status}"


# ---------------------------------------------------------------- pravljenje


@transaction.atomic
def start(persona, goal: str, steps: list[dict], *, actor: str, run=None,
          now: datetime | None = None) -> AgentPlan:
    """Pravi plan i njegove korake. Svaki korak: {handler, type, description, input}."""
    load_handlers()
    now = now or timezone.now()
    if not steps:
        raise PlanError("VALIDATION_ERROR", "Plan bez koraka nema smisla.")
    if len(steps) > MAX_STEPS:
        raise PlanError("VALIDATION_ERROR", f"Najviše {MAX_STEPS} koraka po planu.")
    unknown = [s["handler"] for s in steps if s.get("handler") not in _HANDLERS]
    if unknown:
        raise PlanError("VALIDATION_ERROR", f"Nepoznat obrađivač: {unknown}")

    plan = AgentPlan.objects.create(
        public_id=I.ulid_public_id(I.EntityKind.AGENT_PLAN, now), persona=persona, run=run,
        goal=goal[:2000], status=PS.ACTIVE.value)
    previous = None
    for i, spec in enumerate(steps, start=1):
        previous = PlanStep.objects.create(
            plan=plan, sequence=i, step_type=spec.get("type", E.StepType.ACTION.value),
            description=spec.get("description", "")[:500], depends_on=previous,
            status=SS.READY.value if i == 1 else SS.PENDING.value,
            input_json={"handler": spec["handler"], **(spec.get("input") or {})})
    audit.record("plan.started", persona=persona,
                 details={"plan": plan.public_id, "goal": goal[:200],
                          "steps": len(steps), "actor": actor})
    return plan


# ---------------------------------------------------------------- izvršavanje


def _next_step(plan: AgentPlan) -> PlanStep | None:
    for s in plan.steps.order_by("sequence"):
        if s.status in (SS.DONE.value, SS.SKIPPED.value):
            continue
        if s.status == SS.RUNNING.value:      # čeka odobrenje — plan je pauziran
            return None
        if s.depends_on_id:
            dep = PlanStep.objects.get(pk=s.depends_on_id)
            if dep.status not in (SS.DONE.value, SS.SKIPPED.value):
                return None
        return s
    return None


def _finish(plan: AgentPlan, status: E.PlanStatus, *, reason: str = "") -> None:
    AgentPlan.objects.filter(pk=plan.pk).update(status=status.value)
    plan.status = status.value
    audit.record("plan.finished", persona=plan.persona,
                 details={"plan": plan.public_id, "status": status.value,
                          "reason": reason[:200]})
    _resume_parent(plan, status, reason)


def _resume_parent(child: AgentPlan, status: E.PlanStatus, reason: str) -> None:
    """Zadatak predat drugom agentu vraća se onome ko ga je zadao (ADR-0022)."""
    step = PlanStep.objects.filter(
        status=SS.RUNNING.value, output_json__waiting_for_plan=child.public_id).first()
    if step is None:
        return
    done = status == E.PlanStatus.COMPLETED
    reason = reason or failure_reason(child)
    out = {**(step.output_json or {}), "child_status": status.value, "reason": reason[:300]}
    PlanStep.objects.filter(pk=step.pk).update(
        status=SS.DONE.value if done else SS.FAILED.value, output_json=out)
    parent = step.plan
    audit.record("plan.handback", persona=parent.persona,
                 details={"plan": parent.public_id, "child": child.public_id,
                          "status": status.value})
    if done:
        advance(parent)
    else:
        _finish(parent, E.PlanStatus.ABANDONED,
                reason=f"Izvršilac nije završio: {reason}"[:300])


def advance(plan: AgentPlan, *, now: datetime | None = None) -> AgentPlan:
    """Izvršava korake dok ne naiđe na čekanje, grešku ili kraj."""
    load_handlers()
    now = now or timezone.now()
    for _ in range(MAX_PER_PASS):
        plan.refresh_from_db()
        if plan.status != PS.ACTIVE.value:
            return plan
        step = _next_step(plan)
        if step is None:
            if not plan.steps.exclude(
                    status__in=(SS.DONE.value, SS.SKIPPED.value)).exists():
                _finish(plan, PS.COMPLETED)
            return plan

        fn = _HANDLERS.get((step.input_json or {}).get("handler", ""))
        if fn is None:
            PlanStep.objects.filter(pk=step.pk).update(status=SS.FAILED.value)
            _finish(plan, PS.ABANDONED, reason="Nepoznat obrađivač koraka.")
            return plan

        PlanStep.objects.filter(pk=step.pk).update(status=SS.RUNNING.value)
        try:
            result = fn(step, state(plan))
        except Exception as e:  # noqa: BLE001 — kvar koraka ne ruši ceo sistem
            result = Failed(f"{type(e).__name__}: {e}"[:300])

        if isinstance(result, Done):
            PlanStep.objects.filter(pk=step.pk).update(
                status=SS.DONE.value, output_json=result.output)
        elif isinstance(result, Delegated):
            # Veza se upisuje **pre** nego što izvršilac krene: po njoj se meri
            # dubina lanca i po njoj se posao vraća nalogodavcu (ADR-0022).
            PlanStep.objects.filter(pk=step.pk).update(
                status=SS.RUNNING.value,
                output_json={"waiting_for_plan": result.plan.public_id,
                             "worker": result.plan.persona.public_id, "note": result.note})
            audit.record("plan.delegated", persona=plan.persona,
                         details={"plan": plan.public_id, "step": step.sequence,
                                  "child": result.plan.public_id,
                                  "worker": result.plan.persona.public_id})
            advance(result.plan, now=now)
            return plan
        elif isinstance(result, Waiting):
            PlanStep.objects.filter(pk=step.pk).update(
                status=SS.RUNNING.value,
                output_json={"waiting_for": result.action.public_id, "note": result.note})
            audit.record("plan.paused", persona=plan.persona,
                         action=result.action,
                         details={"plan": plan.public_id, "step": step.sequence,
                                  "action": result.action.public_id})
            return plan
        else:
            PlanStep.objects.filter(pk=step.pk).update(
                status=SS.FAILED.value, output_json={"reason": result.reason})
            _finish(plan, PS.ABANDONED, reason=result.reason)
            return plan
    return plan


# ---------------------------------------------------------------- nastavak


def step_waiting_for(action: Action) -> PlanStep | None:
    return PlanStep.objects.filter(
        status=SS.RUNNING.value, output_json__waiting_for=action.public_id).first()


def on_action_decided(action: Action, *, approved: bool, reason: str = "",
                      now: datetime | None = None) -> AgentPlan | None:
    """Odluka čoveka nastavlja plan ili ga zaustavlja — sa zapisanim razlogom."""
    step = step_waiting_for(action)
    if step is None:
        return None
    now = now or timezone.now()
    plan = step.plan
    out = {**(step.output_json or {}), "decision": "approved" if approved else "rejected",
           "reason": reason[:300]}
    if approved:
        PlanStep.objects.filter(pk=step.pk).update(status=SS.DONE.value, output_json=out)
        audit.record("plan.resumed", persona=plan.persona, action=action,
                     details={"plan": plan.public_id, "step": step.sequence})
        return advance(plan, now=now)
    PlanStep.objects.filter(pk=step.pk).update(status=SS.FAILED.value, output_json=out)
    _finish(plan, PS.ABANDONED, reason=reason or "Odbijeno bez razloga.")
    return plan


def failure_reason(plan: AgentPlan) -> str:
    """Razlog iz koraka koji je pao — da se do nalogodavca vrati šta je stvarno bilo."""
    step = plan.steps.filter(status=SS.FAILED.value).order_by("sequence").first()
    return (step.output_json or {}).get("reason", "") if step else ""


def parent_of(plan: AgentPlan) -> AgentPlan | None:
    """Plan nalogodavca, ako je ovaj plan nekome zadat (ADR-0022)."""
    step = PlanStep.objects.filter(
        output_json__waiting_for_plan=plan.public_id).select_related(
        "plan", "plan__persona").first()
    return step.plan if step else None


def depth_of(plan: AgentPlan, limit: int = 10) -> int:
    """Koliko je puta ovaj plan predat nadole. Plan bez nalogodavca je dubina 0."""
    depth, current = 0, plan
    while depth < limit:
        parent = parent_of(current)
        if parent is None:
            return depth
        depth += 1
        current = parent
    return depth


@handler("plan.note")
def _step_note(step: PlanStep, state: dict) -> Outcome:
    """Beleška u planu — korak bez spoljašnjeg efekta.

    Koristi se da se vidi da je plan nastavljen posle čekanja ili posle
    izvršioca. Ne radi ništa i ne sme da radi ništa.
    """
    return Done({"note": (step.input_json or {}).get("note", step.description)[:300]})


@handler("org.delegate")
def _step_delegate(step: PlanStep, state: dict) -> Outcome:
    """Zadaje korak izvršiocu iz organizacije i čeka njegov plan.

    Delegiranje ne daje nikakvu dozvolu: izvršilac radi sa svojim poverenjem,
    svojim sposobnostima i svojim odobrenjima (ADR-0017).
    """
    from apps.personas.models import Persona
    from apps.personas.org import can_delegate

    spec = step.input_json or {}
    worker = Persona.objects.filter(public_id=spec.get("to", "")).first()
    if worker is None:
        return Failed(f"Nema agenta {spec.get('to', '')}.")
    why = can_delegate(step.plan.persona, worker)
    if why:
        return Failed(why)
    if depth_of(step.plan) + 1 >= MAX_DELEGATION_DEPTH:
        return Failed(f"Lanac delegiranja je dublji od {MAX_DELEGATION_DEPTH} nivoa.")
    sub = spec.get("steps") or []
    if not sub:
        return Failed("Zadatak bez koraka.")
    child = start(worker, spec.get("goal", step.description)[:2000], sub,
                  actor=f"agent:{step.plan.persona.public_id}", run=step.plan.run)
    # Motor pokreće izvršioca tek pošto upiše vezu; kad ovaj završi, posao se
    # sam vraća na ovaj korak (`_resume_parent`).
    return Delegated(child, note=f"Zadato: {worker.display_name}")


def active_for(persona, limit: int = 10) -> list[AgentPlan]:
    return list(AgentPlan.objects.filter(persona=persona)
                .exclude(status=PS.DRAFT.value).order_by("-created_at")[:limit])
