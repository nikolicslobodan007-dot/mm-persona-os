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
class Failed:
    """Korak ne može da se završi. Plan staje, razlog se zapisuje."""

    reason: str


Outcome = Done | Waiting | Failed
Handler = Callable[[PlanStep, dict], Outcome]
_HANDLERS: dict[str, Handler] = {}


def handler(name: str) -> Callable[[Handler], Handler]:
    """Registruje obrađivač koraka. `input_json["handler"]` bira koji se zove."""

    def wrap(fn: Handler) -> Handler:
        _HANDLERS[name] = fn
        return fn

    return wrap


def registered() -> list[str]:
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


def advance(plan: AgentPlan, *, now: datetime | None = None) -> AgentPlan:
    """Izvršava korake dok ne naiđe na čekanje, grešku ili kraj."""
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


def active_for(persona, limit: int = 10) -> list[AgentPlan]:
    return list(AgentPlan.objects.filter(persona=persona)
                .exclude(status=PS.DRAFT.value).order_by("-created_at")[:limit])
