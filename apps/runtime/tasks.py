"""Celery taskovi runtime-a. Canon §11.3, §12.3 · ADR-0008.

    runtime.execute(job_id)     queue posla (browser / mail / channel)
    runtime.dispatch_due        beat 15 s, `control` — šalje dospele poslove
    runtime.reap_leases         beat 30 s, `maintenance` — izgubljeni worker-i
    runtime.reconcile           beat 60 s, `maintenance` — UNKNOWN_EFFECT
"""

from __future__ import annotations

from api.context import bind
from apps.runtime import executor
from config.celery import app


@app.task(name="runtime.execute", acks_late=True)
def execute(job_id: str) -> str | None:
    job = executor.execute_job(job_id)
    return job.status if job else None


@app.task(name="runtime.dispatch_due")
def dispatch_due() -> int:
    jobs = executor.due_jobs()
    for job in jobs:
        execute.apply_async(args=[str(job.pk)], queue=job.queue)
    return len(jobs)


@app.task(name="runtime.reap_leases")
def reap_leases() -> int:
    with bind(actor_id="service:runtime"):
        return executor.reap_leases()


@app.task(name="runtime.reconcile")
def reconcile() -> int:
    with bind(actor_id="service:runtime"):
        return executor.run_reconcile()
