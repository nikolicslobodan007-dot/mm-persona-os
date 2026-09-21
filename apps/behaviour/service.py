"""Buđenje persone nad bazom. Behaviour v0.1 §17–§20, Canon §4.3, §11.

`wake()` je jedina funkcija koja menja `BehaviourState`. Tok u jednoj
transakciji:

  1. Zaključaj red stanja (`SELECT … FOR UPDATE`). To je lease iz §20:
     dva workera ne mogu istovremeno da računaju istu personu, a ako worker
     padne usred posla, transakcija se poništi i brava nestaje sama — nema
     zaglavljenog lease-a koji neko mora da oslobodi.
  2. Ako run sa istim `wake_key` već postoji, vrati njega (§18 idempotency).
  3. `engine.decide()` — čista odluka.
  4. Upiši `AgentRun` (sa odlukom i razlogom), `StateDelta` po pravilu,
     novo stanje uz proveru `state_version`, plan ako je ACT, i evente.

Eventi idu kroz outbox iz iste transakcije (ADR-0004): ako se promena
poništi, poništavaju se i eventi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from api.context import bind, current
from apps.behaviour import engine, routines
from apps.behaviour.clock import local, seed_for
from apps.behaviour.models import BehaviourState, RoutineTemplate, StateDelta, WorldEvent
from apps.observability import bus
from apps.orchestration.models import AgentPlan, AgentRun, PlanStep
from apps.personas.models import Persona
from common import enums as E
from common import ids as I

#: Behaviour v0.1 §26 — dnevni budžet pažnje ako persona nema svoj.
DEFAULT_ATTENTION_DAILY = Decimal("8.00")

_STEP_TYPE = {
    E.ActivityKind.READ: E.StepType.RETRIEVE,
    E.ActivityKind.RESEARCH: E.StepType.RETRIEVE,
    E.ActivityKind.WORK: E.StepType.THINK,
    E.ActivityKind.POST: E.StepType.CREATE,
    E.ActivityKind.SOCIAL: E.StepType.REVIEW,
    E.ActivityKind.INBOX: E.StepType.REVIEW,
}


class PersonaBusy(Exception):
    """Persona nije u stanju koje dozvoljava ovo buđenje."""


def load_windows(persona: Persona, on: datetime) -> list[routines.Window]:
    d = local(on, persona.timezone).date()
    out: list[routines.Window] = []
    templates = RoutineTemplate.objects.filter(persona=persona, is_enabled=True).prefetch_related(
        "windows"
    )
    for t in templates:
        if (t.active_from and d < t.active_from) or (t.active_to and d > t.active_to):
            continue
        for w in t.windows.all():
            try:
                kind = E.ActivityKind(w.activity_type)
            except ValueError:
                continue  # nepoznata vrsta se ne izvršava (ADR-0005)
            out.append(routines.Window(
                id=str(w.id), template=t.name, day_mask=t.day_mask,
                template_priority=t.priority, kind=kind, start=w.start_local,
                end=w.end_local, probability=w.probability, constraints=w.constraints_json,
            ))
    return out


def _state_dict(s: BehaviourState) -> dict:
    out = {f: getattr(s, f) for f in engine.reducer.STATE_FIELDS}
    out["ext"] = s.state_ext or {}
    return out


def _trace_uuid(hex_id: str) -> uuid.UUID:
    return uuid.UUID(hex=hex_id)


def wake(
    persona: Persona,
    reason: E.WakePriority,
    *,
    now: datetime | None = None,
    wake_key: str | None = None,
    event: WorldEvent | None = None,
    relevance: float | None = None,
    actor_id: str = "service:behaviour",
    seed: int | None = None,
) -> AgentRun:
    now = now or timezone.now()
    ctx = current()
    trace = ctx.trace_id if "trace_id" not in ctx.generated else None
    with bind(actor_id=ctx.principal or actor_id, trace_id=trace), transaction.atomic():
        state = BehaviourState.objects.select_for_update().get(persona=persona)
        if wake_key:
            existing = AgentRun.objects.filter(wake_key=wake_key).first()
            if existing:
                return existing

        if seed is None:
            seed = seed_for(local(now, persona.timezone).date())
        ext = state.state_ext or {}
        snap = engine.Snapshot(
            persona_id=persona.public_id,
            status=E.PersonaStatus(persona.status),
            tz=persona.timezone,
            state=_state_dict(state),
            last_state_at=state.last_state_event_at,
            attention_daily=Decimal(str(ext.get("attention_daily", DEFAULT_ATTENTION_DAILY))),
            windows=load_windows(persona, now),
            now=now,
            reason=reason,
            seed=seed,
            event=(engine.PendingEvent(event.public_id, relevance or 0.0) if event else None),
        )
        d = engine.decide(snap)
        return _persist(persona, state, d, reason, seed, now, wake_key, event, relevance)


def _persist(persona, state, d: engine.Decision, reason, seed, now, wake_key, event,
             relevance: float | None = None) -> AgentRun:
    trace_hex = current().trace_id
    run = AgentRun.objects.create(
        public_id=I.ulid_public_id(I.EntityKind.AGENT_RUN, now),
        persona=persona,
        trigger_event=event,
        wake_priority=reason.value,
        status=E.RunStatus.COMPLETED,
        started_at=now,
        ended_at=now,
        decisions_count=1,
        trace_id=_trace_uuid(trace_hex),
        summary_json=d.summary(seed),
        wake_key=wake_key,
        decision=d.decision.value,
        reason_code=d.reason.value,
    )
    bus.emit("persona.woken",
             {"wake_priority": E.WAKE_PRIORITY_VALUE[reason], "reason": d.reason.value},
             persona_id=persona.public_id, run_id=run.public_id)

    version = state.state_version
    deltas: dict[str, list[str]] = {}
    for (rule, _ctx), r in zip(d.steps, d.results, strict=True):
        StateDelta.objects.create(
            persona=persona, run=run, world_event=event, reducer_key=rule,
            from_version=version, to_version=version + 1, changes=r.changes,
            occurred_at=now, trace_id=run.trace_id,
        )
        version += 1
        for k, (before, after) in r.changes.items():
            deltas[k] = [deltas.get(k, [before])[0], after]

    fields = {f: d.state[f] for f in engine.reducer.STATE_FIELDS} if d.results else {}
    if d.results:
        ext = dict(d.state["ext"])
        ext.setdefault("attention_daily", str(
            (state.state_ext or {}).get("attention_daily", DEFAULT_ATTENTION_DAILY)))
        fields["state_ext"] = ext
    fields.update(
        next_wake_at=d.next_wake_at,
        wake_priority=E.WAKE_PRIORITY_VALUE[d.next_wake_priority],
        last_state_event_at=now,
    )
    # Canon §11.1 — nikad „last write wins". Pod bravom ovo uvek uspeva;
    # provera ostaje da bi svaki drugi pisac (i budući kod) morao kroz nju.
    updated = BehaviourState.objects.filter(
        persona=persona, state_version=state.state_version
    ).update(state_version=F("state_version") + len(d.results), **fields)
    if updated != 1:
        raise RuntimeError(f"state_version sukob za {persona.public_id}")

    if d.results:
        payload = {"state_version": version, "deltas": deltas}
        if d.next_wake_at:
            payload["next_wake_at"] = d.next_wake_at.isoformat().replace("+00:00", "Z")
        bus.emit("behaviour.state.recomputed", payload,
                 persona_id=persona.public_id, run_id=run.public_id)

    if d.decision == E.WakeDecision.ACT and d.kind:
        plan = AgentPlan.objects.create(
            public_id=I.ulid_public_id(I.EntityKind.AGENT_PLAN, now),
            persona=persona, run=run, trigger_event=event,
            goal=f"{d.reason.value}: {d.kind.value}"
                 + (f" ({d.window.template} {d.window.start:%H:%M}–{d.window.end:%H:%M})"
                    if d.window else ""),
            status=E.PlanStatus.COMPLETED,
            priority=E.WAKE_PRIORITY_VALUE[reason],
        )
        PlanStep.objects.create(
            plan=plan, sequence=1, step_type=_STEP_TYPE[d.kind].value,
            description=("Nacrt objave; objava ide kroz policy i odobrenje (F7)."
                         if d.kind == E.ActivityKind.POST else
                         f"Interna aktivnost '{d.kind.value}' — bez spoljnog efekta."),
            status=E.StepStatus.DONE,
            input_json={"activity": d.kind.value},
            output_json={"attention_cost": E.ACTIVITY_ATTENTION_COST[d.kind]},
        )
        bus.emit("plan.created", {"plan_id": plan.public_id, "step_count": 1},
                 persona_id=persona.public_id, run_id=run.public_id)
    _remember(persona, run, d, event, now, relevance or 0.0)
    if d.decision == E.WakeDecision.ACT and d.kind == E.ActivityKind.POST:
        # F7 (ADR-0009): prozor „post” → nacrt i predlog objave, POSLE commit-a.
        # Nacrt može da pozove model; ne sme da drži bravu stanja persone.
        from apps.content.planner import schedule_draft

        run_pk = run.pk
        transaction.on_commit(lambda: schedule_draft(run_pk))
    return run


_ACTIVITY_TITLE = {
    E.ActivityKind.READ: "Čitanje", E.ActivityKind.RESEARCH: "Istraživanje",
    E.ActivityKind.WORK: "Radni blok", E.ActivityKind.POST: "Nacrt objave",
    E.ActivityKind.SOCIAL: "Društveni blok", E.ActivityKind.INBOX: "Pregled pošte",
}


def _remember(persona, run, d: engine.Decision, event, now, relevance: float) -> None:
    """F4 (ADR-0006): šta je persona uradila postaje epizoda. Eligibility
    odlučuje da li je vredno pamćenja; dnevna konsolidacija ih sažima."""
    from apps.memory.writer import MemoryInput, MemoryRejected, write

    payload = (event.payload or {}) if event else {}
    topics = [str(t) for t in payload.get("topics", [])]
    synthetic = payload.get("source") == "simulation"
    kind = E.SourceKind.SYNTHETIC_WORLD_EVENT if synthetic else E.SourceKind.SYSTEM_OBSERVATION
    if d.decision == E.WakeDecision.ACT and d.kind:
        title = (f"Pročitala: {event.event_type}" if event else _ACTIVITY_TITLE[d.kind])
        body = (f"Teme: {', '.join(topics)}." if topics else
                f"{_ACTIVITY_TITLE[d.kind]} u prozoru {d.window.template} "
                f"{d.window.start:%H:%M}–{d.window.end:%H:%M}." if d.window else title)
        salience = relevance if event else 0.35
    elif d.reason == E.DecisionReason.EVENT_DEFERRED and event:
        title, body, salience = (f"Zapažena vest, odložena: {event.event_type}",
                                 f"Teme: {', '.join(topics)}. Odložila jer je bila zauzeta.",
                                 relevance * 0.8)
    else:
        return
    try:
        write(persona, MemoryInput(
            memory_type=E.MemoryType.EPISODIC, title=title, content=body,
            source_kind=kind, provenance=E.Provenance.OBSERVED, salience=salience,
            tags=topics or ([d.kind.value] if d.kind else []), event_time=now,
            source_event_id=f"run:{run.public_id}", source_ref=run.public_id, run=run,
        ), now=now)
    except MemoryRejected:
        pass
