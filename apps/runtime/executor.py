"""Izvršenje akcije. Canon §6.2, §12.2–12.6 · ADR-0008.

    enqueue(action)            ALLOW → WorkerJob (jedini ulaz u red)
    execute_job(job_id)        claim → sesija → gateway → adapter → ishod
    reap_leases()              izgubljen worker → retry ili reconcile
    run_reconcile()            UNKNOWN_EFFECT → da li je efekat nastao

Redosled u `execute_job` je namerno takav da se ništa spolja ne dogodi
pre nego što je u bazi zapisano da će se pokušati:

  1. claim posla (SKIP LOCKED), breaker, sesija (1 write + 3 read po personi);
  2. `gateway.authorize()` — ponovna provera svega, i `dry_run` zastavica;
  3. akcija RUNNING, `ActionAttempt` upisan, `runtime.execution.started`;
  4. adapter — van transakcije, zahtevi samo kroz transport;
  5. ishod → status akcije po Canon §3.9, event, trošak, breaker.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from api import audit
from api.context import bind
from apps.observability import bus
from apps.observability.models import CostLedger
from apps.orchestration.models import Action, ActionAttempt
from apps.policy import gateway
from apps.policy.service import _queue_for, _run_id, open_incident
from apps.runtime import adapters, breaker
from apps.runtime import config as rconfig
from apps.runtime.adapters.base import Exec, Outcome
from apps.runtime.control import CancelToken
from apps.runtime.models import ReconcileTask, RuntimeSession, WorkerJob
from apps.runtime.transport import DryRunTransport, LiveTransport, Transport
from common import enums as E

OC = E.ExecutionOutcome
R = E.RuntimeReason
S = E.ActionStatus
J = E.JobStatus
_ACTIVE_JOB = (J.PENDING.value, J.CLAIMED.value, J.RUNNING.value, J.RETRY.value)
_SESSION_TYPE = {E.QueueName.BROWSER: E.SessionType.BROWSER,
                 E.QueueName.MAIL: E.SessionType.MAIL}


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def kind_of(action_type: str) -> str:
    return "read" if action_type in E.READ_ACTION_TYPES else "write"


def _ts(dt: datetime | None) -> str | None:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


# ---------------------------------------------------------------- red


def enqueue(action: Action, *, now: datetime | None = None) -> WorkerJob | None:
    """Poziva ga policy na ALLOW, unutar iste transakcije. Idempotentno."""
    if action.action_type in E.INTERNAL_ACTION_TYPES:
        return None
    now = now or timezone.now()
    job = WorkerJob.objects.filter(action=action, status__in=_ACTIVE_JOB).first()
    run_after = max(now, action.scheduled_for or now)
    if job:
        if job.status == J.RETRY.value:
            job.run_after = min(job.run_after, run_after)
            job.save(update_fields=["run_after", "updated_at"])
        return job
    kind = kind_of(action.action_type)
    job = WorkerJob.objects.create(
        action=action, job_type=action.action_type,
        queue=_queue_for(action.action_type).value, status=J.PENDING.value,
        max_attempts=E.MAX_ATTEMPTS_BY_KIND[kind], run_after=run_after,
        idempotency_key=action.idempotency_key[:128], payload={"action_id": action.public_id},
        trace_id=action.trace_id,
    )
    if getattr(settings, "RUNTIME_KICK", False):
        from apps.runtime.tasks import execute

        transaction.on_commit(lambda: execute.apply_async(
            args=[str(job.pk)], queue=job.queue, countdown=max(
                0, int((run_after - now).total_seconds()))))
    return job


def due_jobs(now: datetime | None = None, limit: int = 100) -> list[WorkerJob]:
    now = now or timezone.now()
    return list(WorkerJob.objects.filter(status__in=[J.PENDING.value, J.RETRY.value],
                                         run_after__lte=now).order_by("run_after")[:limit])


# ---------------------------------------------------------------- sesija


class Busy(Exception):
    pass


def _open_session(action: Action, wid: str, now: datetime) -> RuntimeSession:
    is_write = kind_of(action.action_type) == "write"
    if not is_write:
        n = RuntimeSession.objects.filter(persona=action.persona, is_write=False,
                                          status=E.SessionStatus.OPEN.value).count()
        if n >= E.MAX_READ_SESSIONS_PER_PERSONA:
            raise Busy("read")
    acc = action.channel_account
    try:
        with transaction.atomic():
            return RuntimeSession.objects.create(
                persona=action.persona,
                session_type=_SESSION_TYPE.get(_queue_for(action.action_type),
                                               E.SessionType.TOOL).value,
                browser_profile=acc.browser_profile if acc else None, run=action.run,
                is_write=is_write, worker_id=wid, status=E.SessionStatus.OPEN.value,
                started_at=now, heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=E.LEASE_TTL_SECONDS),
                trace_id=action.trace_id,
            )
    except IntegrityError as e:
        raise Busy("write") from e


def _close_session(session: RuntimeSession | None, status: E.SessionStatus, now: datetime):
    if session is None:
        return
    RuntimeSession.objects.filter(pk=session.pk, status=E.SessionStatus.OPEN.value).update(
        status=status.value, ended_at=now)


# ---------------------------------------------------------------- izvršenje


def transport_for(dry_run: bool) -> Transport:
    return DryRunTransport() if dry_run else LiveTransport()


def execute_job(job_id, *, wid: str | None = None, now: datetime | None = None,
                transport_factory=transport_for, clock=None) -> WorkerJob | None:
    wid = wid or worker_id()
    now = now or timezone.now()

    # 1. claim
    with transaction.atomic():
        job = (WorkerJob.objects.select_for_update(skip_locked=True)
               .filter(pk=job_id, status__in=[J.PENDING.value, J.RETRY.value],
                       run_after__lte=now).first())
        if job is None:
            return None
        action = Action.objects.select_for_update(of=("self",)).select_related(
            "persona", "channel_account", "run").get(pk=job.action_id)
        if action.status not in (S.QUEUED.value, S.RETRY_WAIT.value):
            job.status, job.last_error = J.FAILED.value, f"akcija je {action.status}"
            job.save(update_fields=["status", "last_error", "updated_at"])
            return job
        acc = action.channel_account
        adapter, why_code, why = adapters.resolve(acc.channel_type if acc else None,
                                                  action.action_type)
        if adapter is not None:
            ok, retry_at = breaker.allow(adapter.key, acc, now)
            if not ok:
                job.run_after, job.last_error = retry_at, "BREAKER_OPEN"
                job.save(update_fields=["run_after", "last_error", "updated_at"])
                return job
        try:
            session = _open_session(action, wid, now)
        except Busy:
            job.run_after = now + timedelta(seconds=10)
            job.last_error = "PERSONA_SESSION_BUSY"
            job.save(update_fields=["run_after", "last_error", "updated_at"])
            return job
        job.status, job.attempt, job.worker_id = J.RUNNING.value, job.attempt + 1, wid
        job.locked_at, job.session = now, session
        job.lease_expires_at = now + timedelta(seconds=E.LEASE_TTL_SECONDS)
        job.save()

    trace = action.trace_id.hex if action.trace_id else None
    with bind(actor_id="service:runtime", trace_id=trace):
        # 2. gateway
        try:
            contract = gateway.authorize(action, now=now)
        except gateway.GatewayRefused as refused:
            return _refused(job, action, session, refused, now)

        # 3. RUNNING + pokušaj
        with transaction.atomic():
            action = Action.objects.select_for_update(of=("self",)).select_related(
                "persona", "channel_account", "run").get(pk=action.pk)
            action.status = S.RUNNING.value
            action.started_at = action.started_at or now
            action.save(update_fields=["status", "started_at", "updated_at"])
            attempt = ActionAttempt.objects.create(
                action=action, attempt_number=action.attempts.count() + 1, started_at=now,
                worker_id=wid, session=session,
                payload={"dry_run": contract["dry_run"], "contract": contract})
            bus.emit("runtime.execution.started",
                     {"action_id": action.public_id, "attempt": attempt.attempt_number,
                      "worker_id": wid},
                     persona_id=action.persona.public_id, run_id=_run_id(action))

        # 4. adapter
        transport = transport_factory(contract["dry_run"])
        token = CancelToken(action, session, **({"clock": clock} if clock else {}))
        if adapter is None:
            out = Outcome(OC.CAPABILITY_UNAVAILABLE, why_code, detail=why)
            x = None
        else:
            x = Exec(action=action, account=acc, contract=contract, transport=transport,
                     token=token, now=now)
            try:
                out = adapter.run(x)
            except Exception as e:  # noqa: BLE001 — greška adaptera ne sme da ostavi RUNNING
                out = Outcome(OC.UNKNOWN_EFFECT if x.write_sent else OC.RETRYABLE_ERROR,
                              R.ADAPTER_ERROR.value, detail=f"{type(e).__name__}: {e}"[:500])
        if out.outcome == OC.SUCCEEDED and contract["dry_run"] and out.reason_code != \
                R.SANDBOX.value:
            out.reason_code, out.external_ref = R.DRY_RUN.value, None
        return finalize(job, action, attempt, session, out, now=max(timezone.now(), now),
                        dry_run=contract["dry_run"],
                        requests=x.sent if x else [], token=token,
                        adapter_key=adapter.key if adapter else None)


def _refused(job, action, session, refused, now) -> WorkerJob:
    with transaction.atomic():
        _close_session(session, E.SessionStatus.CLOSED, now)
        if refused.reason_code == "DECISION_EXPIRED":
            # Odluka je istekla dok je posao čekao (npr. plafon mejlboksa) —
            # nova evaluacija; ako je ALLOW, _decide pravi novi posao.
            job.status, job.last_error = J.FAILED.value, "DECISION_EXPIRED → reevaluate"
            job.save(update_fields=["status", "last_error", "updated_at"])
            transaction.on_commit(lambda: _reevaluate(action.pk))
            return job
        job.status, job.last_error = J.FAILED.value, f"GATEWAY:{refused.reason_code}"
        job.save(update_fields=["status", "last_error", "updated_at"])
    return job


def _reevaluate(action_pk) -> None:
    from apps.policy.service import PolicyError, reevaluate

    try:
        reevaluate(Action.objects.get(pk=action_pk))
    except PolicyError:
        pass


def _backoff(kind: str, attempt: int, retry_after: int) -> int:
    steps = E.RETRY_BACKOFF_SECONDS[kind]
    return max(steps[min(attempt, len(steps)) - 1], retry_after)


def finalize(job: WorkerJob, action: Action, attempt: ActionAttempt,
             session: RuntimeSession | None, out: Outcome, *, now: datetime, dry_run: bool,
             requests: list, token: CancelToken | None = None,
             adapter_key: str | None = None) -> WorkerJob:
    with transaction.atomic():
        action = Action.objects.select_for_update(of=("self",)).select_related(
            "persona", "channel_account", "run").get(pk=action.pk)
        pid, rid = action.persona.public_id, _run_id(action)
        duration = token.elapsed_ms() if token else None
        attempt.outcome, attempt.reason_code = out.outcome.value, out.reason_code[:48]
        attempt.finished_at, attempt.duration_ms = now, duration
        attempt.evidence_level = (E.EvidenceLevel.NONE if dry_run else out.evidence_level).value
        attempt.error_detail = out.detail
        attempt.payload = {**(attempt.payload or {}), "requests": requests,
                           "result": out.result,
                           "estimated_cost_usd": str(sum((c.usd for c in out.costs),
                                                         Decimal(0)))}
        attempt.save()

        kind = kind_of(action.action_type)
        killed = out.reason_code == R.KILL_SWITCH.value
        o = out.outcome
        if killed and o == OC.ABORTED_SAFE:
            _finish(action, S.BLOCKED, "KILL_SWITCH", now)
            bus.emit("action.blocked", {"action_id": action.public_id, "outcome": o.value,
                                        "reason_code": out.reason_code},
                     persona_id=pid, run_id=rid)
            ks = token.stopped_by if token else None
            audit.record("runtime.stopped_in_flight", severity=E.AuditSeverity.WARNING,
                         details={"action_id": action.public_id,
                                  "stop_latency_ms": int((now - ks.activated_at)
                                                         .total_seconds() * 1000)
                                  if ks else None})
            job.status = J.FAILED.value
        elif o in (OC.RETRYABLE_ERROR, OC.ABORTED_SAFE):
            if job.attempt < job.max_attempts:
                action.status, action.error_code = S.RETRY_WAIT.value, out.reason_code[:80]
                action.save(update_fields=["status", "error_code", "updated_at"])
                job.status = J.RETRY.value
                job.run_after = now + timedelta(seconds=_backoff(kind, job.attempt,
                                                                 out.retry_after_s))
            else:
                _finish(action, S.FAILED, R.RETRIES_EXHAUSTED.value, now)
                bus.emit("action.failed", {"action_id": action.public_id, "outcome": o.value,
                                           "reason_code": out.reason_code},
                         persona_id=pid, run_id=rid)
                job.status = J.FAILED.value
        elif o == OC.UNKNOWN_EFFECT:
            # Canon §12.3 — nikada retry; akcija ostaje RUNNING dok reconcile ne presudi.
            action.error_code = out.reason_code[:80]
            action.save(update_fields=["error_code", "updated_at"])
            ReconcileTask.objects.create(
                action=action, attempt=attempt, status=E.ReconcileStatus.PENDING.value,
                reason=out.reason_code, check_method=adapter_key or "",
                scheduled_for=now + timedelta(seconds=E.RECONCILE_DELAY_SECONDS),
                trace_id=action.trace_id)
            job.status = J.FAILED.value
        elif o == OC.SUCCEEDED:
            action.status, action.completed_at, action.error_code = S.SUCCEEDED.value, now, ""
            action.result_json = {"dry_run": dry_run, "external_ref": out.external_ref,
                                  "reason_code": out.reason_code, **out.result}
            action.save(update_fields=["status", "completed_at", "error_code", "result_json",
                                       "updated_at"])
            bus.emit("action.succeeded", {"action_id": action.public_id,
                                          "external_ref": out.external_ref},
                     persona_id=pid, run_id=rid)
            if not dry_run:
                _record_costs(action, out, now)
            job.status = J.SUCCEEDED.value
        else:
            status = E.OUTCOME_TO_STATUS[o] or S.FAILED
            _finish(action, status, out.reason_code, now)
            event = "action.blocked" if status == S.BLOCKED else "action.failed"
            bus.emit(event, {"action_id": action.public_id, "outcome": o.value,
                             "reason_code": out.reason_code}, persona_id=pid, run_id=rid)
            job.status = J.FAILED.value

        job.last_error = "" if o == OC.SUCCEEDED else f"{o.value}:{out.reason_code}"[:500]
        job.lease_expires_at = None
        job.save(update_fields=["status", "run_after", "last_error", "lease_expires_at",
                                "updated_at"])
        _close_session(session, E.SessionStatus.ABORTED if killed else E.SessionStatus.CLOSED,
                       now)
        if adapter_key:
            breaker.record(adapter_key, action.channel_account, now=now, persona=action.persona,
                           ok=not breaker.is_failure(o, out.reason_code))
        bus.emit("runtime.execution.finished",
                 {"action_id": action.public_id, "attempt": attempt.attempt_number,
                  "outcome": o.value, "duration_ms": duration or 0},
                 persona_id=pid, run_id=rid)
    return job


def _finish(action: Action, status: S, code: str, now: datetime) -> None:
    action.status, action.error_code, action.completed_at = status.value, code[:80], now
    action.save(update_fields=["status", "error_code", "completed_at", "updated_at"])


def _record_costs(action: Action, out: Outcome, now: datetime) -> None:
    fx = rconfig.fx_usd_eur()
    for c in out.costs:
        if c.usd <= 0:
            continue
        cents = int((c.usd * fx * 100).to_integral_value(rounding=ROUND_CEILING))
        usd_minor = int((c.usd * 100).to_integral_value(rounding=ROUND_CEILING))
        CostLedger.objects.create(
            persona=action.persona, run=action.run, action=action,
            cost_bucket=c.bucket.value, provider=c.provider, quantity=c.quantity, unit=c.unit,
            amount_eur_cents=cents, source_currency="USD", source_amount_minor=usd_minor,
            fx_rate=fx, fx_date=now.date(), occurred_at=now, provider_ref=action.public_id)
        bus.emit("cost.recorded", {"bucket": c.bucket.value, "amount_eur_cents": cents,
                                   "source_currency": "USD"},
                 persona_id=action.persona.public_id, run_id=_run_id(action))


# ---------------------------------------------------------------- lease


def reap_leases(now: datetime | None = None) -> int:
    """Canon §12.3: izgubljen heartbeat → čitanje se ponavlja, pisanje ide u reconcile."""
    now = now or timezone.now()
    n = 0
    stale = list(RuntimeSession.objects.filter(status=E.SessionStatus.OPEN.value,
                                               lease_expires_at__lt=now)
                 .values_list("pk", flat=True)[:200])
    for spk in stale:
        with transaction.atomic():
            s = (RuntimeSession.objects.select_for_update(skip_locked=True)
                 .filter(pk=spk, status=E.SessionStatus.OPEN.value).first())
            if s is None:
                continue
            s.status, s.ended_at = E.SessionStatus.EXPIRED.value, now
            s.save(update_fields=["status", "ended_at", "updated_at"])
            jobs = list(WorkerJob.objects.select_for_update().filter(
                session=s, status=J.RUNNING.value))
        for job in jobs:
            action = Action.objects.select_related("persona", "channel_account", "run").get(
                pk=job.action_id)
            attempt = action.attempts.filter(outcome__isnull=True).order_by(
                "-attempt_number").first()
            with bind(actor_id="service:runtime",
                      trace_id=action.trace_id.hex if action.trace_id else None):
                if attempt is None:
                    # Umro pre upisa pokušaja — ništa nije poslato.
                    WorkerJob.objects.filter(pk=job.pk).update(
                        status=J.RETRY.value, run_after=now, last_error="LEASE_LOST")
                    continue
                o = OC.ABORTED_SAFE if kind_of(action.action_type) == "read" \
                    else OC.UNKNOWN_EFFECT
                finalize(job, action, attempt, None, Outcome(o, R.LEASE_LOST.value),
                         now=now, dry_run=bool((attempt.payload or {}).get("dry_run", True)),
                         requests=[])
            n += 1
    return n


# ---------------------------------------------------------------- reconcile


def run_reconcile(now: datetime | None = None, *, transport_factory=transport_for) -> int:
    now = now or timezone.now()
    done = 0
    for pk in ReconcileTask.objects.filter(status=E.ReconcileStatus.PENDING.value,
                                           scheduled_for__lte=now).values_list("pk", flat=True):
        with transaction.atomic():
            t = (ReconcileTask.objects.select_for_update(skip_locked=True, of=("self",))
                 .filter(pk=pk, status=E.ReconcileStatus.PENDING.value)
                 .select_related("action__persona", "action__channel_account", "attempt")
                 .first())
            if t is None:
                continue
            t.status = E.ReconcileStatus.IN_PROGRESS.value
            t.save(update_fields=["status", "updated_at"])
        action = t.action
        with bind(actor_id="service:runtime",
                  trace_id=action.trace_id.hex if action.trace_id else None):
            _reconcile_one(t, action, now, transport_factory)
        done += 1
    return done


def _reconcile_one(t: ReconcileTask, action: Action, now: datetime, transport_factory):
    acc = action.channel_account
    adapter, _, _ = adapters.resolve(acc.channel_type if acc else None, action.action_type)
    dry = bool((t.attempt.payload or {}).get("dry_run", True))
    status = E.ReconcileStatus.UNRESOLVED
    if adapter is not None:
        x = Exec(action=action, account=acc, contract={"dry_run": dry},
                 transport=transport_factory(dry), token=CancelToken(action, None,
                                                                     deadline_at=None),
                 now=now)
        x.token.deadline_at = None
        try:
            status = adapter.verify(x)
        except Exception as e:  # noqa: BLE001
            t.checks = {**(t.checks or {}), str(t.attempts + 1): f"{type(e).__name__}"}
    with transaction.atomic():
        t = ReconcileTask.objects.select_for_update().get(pk=t.pk)
        action = Action.objects.select_for_update(of=("self",)).select_related(
            "persona", "run").get(pk=action.pk)
        t.attempts += 1
        pid, rid = action.persona.public_id, _run_id(action)
        if status == E.ReconcileStatus.RESOLVED_EFFECT_PRESENT:
            t.status, t.resolved_at = status.value, now
            action.status, action.completed_at = S.SUCCEEDED.value, now
            action.error_code = R.RECONCILE_EFFECT_PRESENT.value
            action.save(update_fields=["status", "completed_at", "error_code", "updated_at"])
            bus.emit("action.succeeded", {"action_id": action.public_id, "external_ref": None},
                     persona_id=pid, run_id=rid)
        elif status == E.ReconcileStatus.RESOLVED_NO_EFFECT:
            t.status, t.resolved_at = status.value, now
            job = WorkerJob.objects.filter(action=action).order_by("-created_at").first()
            if job and job.attempt < job.max_attempts:
                action.status, action.error_code = S.RETRY_WAIT.value, \
                    R.RECONCILE_NO_EFFECT.value
                action.save(update_fields=["status", "error_code", "updated_at"])
                job.status = J.RETRY.value
                job.run_after = now + timedelta(seconds=E.RETRY_BACKOFF_SECONDS["write"][0])
                job.save(update_fields=["status", "run_after", "updated_at"])
            else:
                _finish(action, S.FAILED, R.RECONCILE_NO_EFFECT.value, now)
                bus.emit("action.failed", {"action_id": action.public_id,
                                           "outcome": OC.UNKNOWN_EFFECT.value,
                                           "reason_code": R.RECONCILE_NO_EFFECT.value},
                         persona_id=pid, run_id=rid)
        elif t.attempts >= E.RECONCILE_MAX_CHECKS:
            t.status = E.ReconcileStatus.UNRESOLVED.value
            _finish(action, S.FAILED, R.RECONCILE_UNRESOLVED.value, now)
            bus.emit("action.failed", {"action_id": action.public_id,
                                       "outcome": OC.UNKNOWN_EFFECT.value,
                                       "reason_code": R.RECONCILE_UNRESOLVED.value},
                     persona_id=pid, run_id=rid)
            open_incident(E.IncidentSeverity.SEV2, "reconcile_unresolved",
                          f"Ne zna se da li je {action.public_id} izvršena — proveriti ručno",
                          persona=action.persona, action=action,
                          reason_code=R.RECONCILE_UNRESOLVED.value, now=now)
        else:
            t.status = E.ReconcileStatus.PENDING.value
            t.scheduled_for = now + timedelta(seconds=60 * t.attempts)
        t.save()


# ---------------------------------------------------------------- pregled


def runtime_overview(now: datetime | None = None) -> dict:
    from django.db.models import Count

    from apps.runtime.models import CircuitBreaker

    now = now or timezone.now()
    jobs = dict(WorkerJob.objects.values_list("status").annotate(n=Count("id"))
                .values_list("status", "n"))
    due = WorkerJob.objects.filter(status__in=[J.PENDING.value, J.RETRY.value],
                                   run_after__lte=now)
    oldest = due.order_by("run_after").values_list("run_after", flat=True).first()
    return {
        "external_actions_enabled": bool(getattr(settings, "GLOBAL_EXTERNAL_ACTIONS_ENABLED",
                                                 False)),
        "jobs": jobs,
        "due": due.count(),
        "oldest_due_age_s": int((now - oldest).total_seconds()) if oldest else 0,
        "running_actions": Action.objects.filter(status=S.RUNNING.value).count(),
        "open_sessions": RuntimeSession.objects.filter(
            status=E.SessionStatus.OPEN.value).count(),
        "reconcile_pending": ReconcileTask.objects.filter(
            status__in=[E.ReconcileStatus.PENDING.value,
                        E.ReconcileStatus.IN_PROGRESS.value]).count(),
        "breakers": [{"adapter": b.adapter_key, "account": b.account.handle if b.account
                      else None, "state": b.state, "opened_at": _ts(b.opened_at)}
                     for b in CircuitBreaker.objects.exclude(state=E.BreakerState.CLOSED.value)
                     .select_related("account")],
    }

