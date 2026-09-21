"""Odluka jednog buđenja. Behaviour v0.1 §3, §6–8, §14, §25.

    decision = decide(snapshot)

Čista funkcija, kao i reducer: dobija sve što joj treba u `Snapshot`-u i
vraća `Decision` — šta je odlučeno, zašto, kojim redom se stanje menja i
kada je sledeće buđenje. Baza, eventi i Celery su u `service.py`.

Redosled provera je namerno fiksan i odgovara §6 (`skip_if`), §8
(budžet, cooldown) i §25 (golden day). Prvo pravilo koje kaže „ne" odlučuje;
razlog se upisuje u run, jer SKIP i DEFER moraju biti merljivi (§30).

Šta F3 NE radi (ADR-0005): ciljevi i njihov utility (§13) nemaju model do
F4/F5; LLM rafinisanje kandidata (§14 korak 5) čeka LLM gateway; spoljna
akcija se nikada ne kreira — `post` je nacrt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from apps.behaviour import reducer, routines
from apps.behaviour.clock import local, roll
from common import enums as E

D = Decimal
MIN_ENERGY = D("0.250")
MAX_COGNITIVE_LOAD = D("0.900")
MAX_STRESS = D("0.850")
#: Koliko se odlaže buđenje kad je persona zauzeta, a prozor još traje.
RETRY_IN_WINDOW = timedelta(minutes=15)


@dataclass
class PendingEvent:
    id: str
    relevance: float


@dataclass
class Snapshot:
    persona_id: str
    status: E.PersonaStatus
    tz: str
    state: dict[str, Any]
    last_state_at: datetime | None
    attention_daily: Decimal
    windows: list[routines.Window]
    now: datetime
    reason: E.WakePriority
    seed: int
    event: PendingEvent | None = None


@dataclass
class Decision:
    decision: E.WakeDecision
    reason: E.DecisionReason
    kind: E.ActivityKind | None
    window: routines.Window | None
    local_date: str
    steps: list[tuple[str, dict]] = field(default_factory=list)
    results: list[reducer.Result] = field(default_factory=list)
    next_wake_at: datetime | None = None
    next_wake_priority: E.WakePriority = E.WakePriority.ROUTINE_WINDOW
    roll: float | None = None

    @property
    def state(self) -> dict[str, Any]:
        return self.results[-1].state if self.results else {}

    def summary(self, seed: int) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason_code": self.reason.value,
            "activity": self.kind.value if self.kind else None,
            "window": (
                {"id": self.window.id, "template": self.window.template,
                 "kind": self.window.kind.value,
                 "start": self.window.start.isoformat(), "end": self.window.end.isoformat(),
                 "probability": str(self.window.probability)}
                if self.window else None
            ),
            "roll": round(self.roll, 6) if self.roll is not None else None,
            "seed": seed,
            "local_date": self.local_date,
            "reducers": [s[0] for s in self.steps],
            "next_wake_at": self.next_wake_at.isoformat() if self.next_wake_at else None,
        }


def _apply(d: Decision, state: dict, event: str, ctx: dict) -> dict:
    r = reducer.reduce(state, event, ctx)
    d.steps.append((event, ctx))
    d.results.append(r)
    return r.state


def _next_routine(snap: Snapshot) -> datetime | None:
    nxt = routines.next_window_start(snap.windows, snap.tz, snap.now)
    return nxt[0] if nxt else None


def decide(snap: Snapshot) -> Decision:
    local_now = local(snap.now, snap.tz)
    local_date = local_now.date().isoformat()
    cur = routines.current_window(snap.windows, snap.tz, snap.now)
    window = cur[0] if cur else None
    d = Decision(E.WakeDecision.SKIP, E.DecisionReason.NO_WINDOW, None, window, local_date)

    if snap.status in (E.PersonaStatus.PAUSED, E.PersonaStatus.SUSPENDED,
                       E.PersonaStatus.ARCHIVED, E.PersonaStatus.DEGRADED):
        d.reason = E.DecisionReason.PERSONA_PAUSED
        return d

    # 1. Vreme je prošlo: novi dan ili proticanje sati od poslednje promene.
    state = snap.state
    day = (state.get("ext") or {}).get("day") or {}
    if day.get("date") != local_date:
        state = _apply(d, state, "day.started",
                       {"local_date": local_date, "attention_daily": str(snap.attention_daily)})
    elif snap.last_state_at and snap.now > snap.last_state_at:
        minutes = int((snap.now - snap.last_state_at).total_seconds() // 60)
        if minutes > 0:
            state = _apply(d, state, "time.elapsed", {"minutes": minutes})

    energy = D(str(state["energy"]))
    attention = D(str(state["attention_remaining"]))
    d.next_wake_at = _next_routine(snap)

    # 2. Relevantan svetski događaj (§12, §25 u 11:48).
    if snap.reason == E.WakePriority.WORLD_EVENT_HIGH and snap.event:
        state = _apply(d, state, "world.event.relevant", {"relevance": snap.event.relevance})
        busy = window is not None and window.kind in (E.ActivityKind.WORK, E.ActivityKind.POST)
        cost = D(E.ACTIVITY_ATTENTION_COST[E.ActivityKind.READ])
        if busy or energy < MIN_ENERGY or attention < cost:
            d.decision, d.reason = E.WakeDecision.DEFER, E.DecisionReason.EVENT_DEFERRED
            return d
        d.decision, d.reason, d.kind = (E.WakeDecision.ACT,
                                        E.DecisionReason.WORLD_EVENT_RELEVANT,
                                        E.ActivityKind.READ)
        _apply(d, state, "activity.completed",
               {"kind": E.ActivityKind.READ.value, "at": snap.now.isoformat(),
                "window_id": None})
        return d

    # 3. Rutinski prozor (§6).
    if window is None:
        d.decision, d.reason = E.WakeDecision.DEFER, E.DecisionReason.NO_WINDOW
        return d
    forced = snap.reason == E.WakePriority.OPERATOR_TASK
    windows_today = ((state.get("ext") or {}).get("day") or {}).get("windows", {})

    def close(reason: E.DecisionReason) -> Decision:
        d.decision, d.reason = E.WakeDecision.SKIP, reason
        _apply(d, state, "window.closed",
               {"window_id": window.id, "decision": E.WakeDecision.SKIP.value})
        return d

    if window.id in windows_today:
        d.reason = E.DecisionReason.WINDOW_LIMIT_REACHED
        return d
    if window.kind == E.ActivityKind.REST:
        return close(E.DecisionReason.REST_WINDOW)

    d.roll = roll(snap.seed, snap.persona_id, local_date, window.id)
    if not forced and d.roll >= float(window.probability):
        return close(E.DecisionReason.ROUTINE_NOT_SELECTED)

    cost = D(E.ACTIVITY_ATTENTION_COST[window.kind])
    if energy < MIN_ENERGY or attention < cost:
        return close(E.DecisionReason.LOW_ENERGY_OR_BUDGET)
    if (D(str(state["cognitive_load"])) > MAX_COGNITIVE_LOAD
            or D(str(state["stress"])) > MAX_STRESS):
        return close(E.DecisionReason.OVERLOADED)

    last = (((state.get("ext") or {}).get("day") or {}).get("last_at") or {}).get(window.kind.value)
    cooldown = timedelta(minutes=E.ACTIVITY_COOLDOWN_MINUTES[window.kind])
    if last and cooldown and snap.now < datetime.fromisoformat(last) + cooldown:
        d.decision, d.reason = E.WakeDecision.DEFER, E.DecisionReason.COOLDOWN_ACTIVE
        retry = datetime.fromisoformat(last) + cooldown
        end = routines.window_end(window, local_now.date(), snap.tz)
        if retry < end:
            d.next_wake_at = retry
        return d

    d.decision, d.kind = E.WakeDecision.ACT, window.kind
    d.reason = E.DecisionReason.OPERATOR_TASK if forced else E.DecisionReason.ROUTINE_WINDOW_DUE
    _apply(d, state, "activity.completed",
           {"kind": window.kind.value, "at": snap.now.isoformat(), "window_id": window.id})
    return d
