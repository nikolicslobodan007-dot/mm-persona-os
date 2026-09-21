"""F3 — Behaviour engine, rutine, scheduler, World Engine. ADR-0005.

Prati acceptance kriterijume Behaviour v0.1 §28 i §30: deterministički
reducer, opsezi stanja, DST, isti seed → iste odluke, SKIP/DEFER su
auditovani, nema duplih run-ova pod konkurencijom, nema spoljnih akcija.
"""

from __future__ import annotations

import io
import threading
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import connection

from apps.behaviour import engine, reducer, routines, scheduler, service, world
from apps.behaviour.clock import roll
from apps.behaviour.models import BehaviourState, StateDelta
from apps.observability.models import EventOutbox
from apps.orchestration.models import Action, AgentPlan, AgentRun
from apps.personas.models import Persona
from common import enums as E
from tests.conftest import requires_db

D = Decimal
BASE = {
    "energy": D("0.700"), "valence": D("0.200"), "arousal": D("0.400"),
    "cognitive_load": D("0.200"), "social_appetite": D("0.500"),
    "curiosity_now": D("0.700"), "focus": D("0.650"), "novelty_need": D("0.450"),
    "stress": D("0.150"), "content_pressure": D("0.300"), "inbox_pressure": D("0.100"),
    "topic_saturation": D("0.100"), "risk_alert": D("0.000"),
    "attention_remaining": D("8.00"), "ext": {},
}
BELGRADE = "Europe/Belgrade"


def _w(kind, start, end, p="1.000", mask=0b1111111, wid=None):
    return routines.Window(
        id=wid or f"w-{kind}-{start}", template="t", day_mask=mask, template_priority=0,
        kind=E.ActivityKind(kind), start=time.fromisoformat(start),
        end=time.fromisoformat(end), probability=D(p),
    )


def _snap(now, windows, state=None, reason=E.WakePriority.ROUTINE_WINDOW, seed=1, **kw):
    return engine.Snapshot(
        persona_id="P-00001", status=kw.pop("status", E.PersonaStatus.ACTIVE), tz=BELGRADE,
        state=state or dict(BASE), last_state_at=None, attention_daily=D("8.00"),
        windows=windows, now=now, reason=reason, seed=seed, **kw,
    )


def _utc(local_str, tz=BELGRADE):
    return datetime.fromisoformat(local_str).replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)


# ---------------------------------------------------------------- reducer


class TestReducer:
    def test_same_input_same_output(self):
        ctx = {"kind": "work", "at": "2026-09-21T08:00:00+00:00", "window_id": "w1"}
        a = reducer.reduce(BASE, "activity.completed", ctx)
        b = reducer.reduce(BASE, "activity.completed", ctx)
        assert a.state == b.state and a.changes == b.changes

    def test_input_is_not_mutated(self):
        before = {k: v for k, v in BASE.items()}
        reducer.reduce(BASE, "day.started", {"local_date": "2026-09-21", "attention_daily": "8"})
        assert BASE == before

    def test_unknown_rule_refused(self):
        with pytest.raises(KeyError):
            reducer.reduce(BASE, "mood.changed", {})

    def test_values_stay_in_range_under_any_sequence(self):
        """Property test (§28): 2000 pseudo-slučajnih pravila, nijedno polje van opsega."""
        s = dict(BASE)
        kinds = [k.value for k in E.ActivityKind]
        for i in range(2000):
            r = roll(7, i)
            if r < 0.6:
                ctx = {"kind": kinds[i % len(kinds)], "at": "x", "window_id": None}
                s = reducer.reduce(s, "activity.completed", ctx).state
            elif r < 0.8:
                s = reducer.reduce(s, "time.elapsed", {"minutes": int(r * 2000)}).state
            elif r < 0.9:
                s = reducer.reduce(s, "world.event.relevant", {"relevance": r}).state
            else:
                s = reducer.reduce(s, "day.started",
                                   {"local_date": str(i), "attention_daily": "8.00"}).state
            for f in reducer.UNIT_FIELDS:
                assert D(0) <= s[f] <= D(1), (i, f, s[f])
            assert D(-1) <= s["valence"] <= D(1)
            assert D(0) <= s["attention_remaining"] <= D(24)

    def test_day_started_resets_budget_and_counters(self):
        s = reducer.reduce(dict(BASE, attention_remaining=D("0.40")), "day.started",
                           {"local_date": "2026-09-22", "attention_daily": "8.00"}).state
        assert s["attention_remaining"] == D("8.00")
        assert s["ext"]["day"] == {"date": "2026-09-22", "counts": {}, "last_at": {}, "windows": {}}


# ---------------------------------------------------------------- vreme i DST


class TestTime:
    @pytest.mark.parametrize("tz, day, expected_utc_hour", [
        ("Europe/Belgrade", date(2026, 10, 24), 6),   # CEST, dan pre prelaza
        ("Europe/Belgrade", date(2026, 10, 26), 7),   # CET, dan posle
        ("Europe/Rome", date(2026, 3, 28), 7),        # CET, dan pre prolećnog prelaza
        ("Europe/Rome", date(2026, 3, 30), 6),        # CEST
        ("UTC", date(2026, 3, 29), 8),
    ])
    def test_window_start_follows_dst(self, tz, day, expected_utc_hour):
        w = _w("read", "08:00", "09:00")
        start, _ = w.bounds_utc(day, ZoneInfo(tz))
        assert start.hour == expected_utc_hour

    def test_next_window_across_dst_night(self):
        w = _w("read", "08:00", "09:00")
        # Subota 24.10. u 22:00 lokalno; noć prelaska na zimsko vreme.
        nxt, _ = routines.next_window_start([w], BELGRADE, _utc("2026-10-24T22:00"))
        assert nxt == datetime(2026, 10, 25, 7, 0, tzinfo=UTC)  # 08:00 CET

    def test_day_mask_respected(self):
        weekday_only = _w("work", "09:00", "10:00", mask=0b0011111)
        nxt, _ = routines.next_window_start([weekday_only], BELGRADE, _utc("2026-09-25T12:00"))
        assert nxt.astimezone(ZoneInfo(BELGRADE)).date() == date(2026, 9, 28)  # ponedeljak


# ---------------------------------------------------------------- engine


class TestEngine:
    def test_golden_evening_skip_low_energy(self):
        """Behaviour v0.1 §28 — energy .24, attention .5, večernji prozor → SKIP."""
        today = {"day": {"date": "2026-09-21", "counts": {}, "last_at": {}, "windows": {}}}
        state = dict(BASE, energy=D("0.240"), attention_remaining=D("0.50"), ext=today)
        evening = [_w("social", "17:00", "18:30")]
        d = engine.decide(_snap(_utc("2026-09-21T17:05"), evening, state))
        assert d.decision == E.WakeDecision.SKIP
        assert d.reason == E.DecisionReason.LOW_ENERGY_OR_BUDGET
        assert d.kind is None
        assert d.next_wake_at is not None and d.next_wake_at > _utc("2026-09-21T17:05")

    def test_rest_window_always_skip(self):
        d = engine.decide(_snap(_utc("2026-09-21T21:05"), [_w("rest", "21:00", "23:00")]))
        assert (d.decision, d.reason) == (E.WakeDecision.SKIP, E.DecisionReason.REST_WINDOW)

    def test_same_seed_same_decisions(self):
        windows = [_w(k, f"{h:02d}:00", f"{h:02d}:59", p="0.500", wid=f"w{h}")
                   for h, k in zip(range(8, 16), ["read", "work", "post", "social"] * 2,
                                   strict=True)]

        def run(seed):
            return [engine.decide(_snap(_utc(f"2026-09-21T{h:02d}:10"), windows, seed=seed))
                    .decision for h in range(8, 16)]
        assert run(42) == run(42)
        assert any(run(s) != run(42) for s in range(1, 20))

    def test_operator_bypasses_roll_not_budget(self):
        w = [_w("work", "09:00", "10:00", p="0.000")]
        assert engine.decide(_snap(_utc("2026-09-21T09:10"), w)).reason == \
            E.DecisionReason.ROUTINE_NOT_SELECTED
        forced = engine.decide(_snap(_utc("2026-09-21T09:10"), w,
                                     reason=E.WakePriority.OPERATOR_TASK))
        assert forced.decision == E.WakeDecision.ACT
        today = {"day": {"date": "2026-09-21", "counts": {}, "last_at": {}, "windows": {}}}
        tired = dict(BASE, attention_remaining=D("1.00"), ext=today)  # rad košta 2.00
        blocked = engine.decide(_snap(_utc("2026-09-21T09:10"), w, tired,
                                      reason=E.WakePriority.OPERATOR_TASK))
        assert blocked.reason == E.DecisionReason.LOW_ENERGY_OR_BUDGET

    def test_window_evaluated_once_per_day(self):
        w = [_w("read", "08:00", "09:30")]
        first = engine.decide(_snap(_utc("2026-09-21T08:05"), w))
        second = engine.decide(_snap(_utc("2026-09-21T08:40"), w, first.state))
        assert first.decision == E.WakeDecision.ACT
        assert second.reason == E.DecisionReason.WINDOW_LIMIT_REACHED
        assert second.results == []  # nije promenio stanje

    def test_cooldown_defers_inside_window(self):
        w1, w2 = _w("read", "08:00", "08:20", wid="a"), _w("read", "08:20", "10:00", wid="b")
        first = engine.decide(_snap(_utc("2026-09-21T08:05"), [w1, w2]))
        second = engine.decide(_snap(_utc("2026-09-21T08:25"), [w1, w2], first.state))
        assert second.reason == E.DecisionReason.COOLDOWN_ACTIVE
        assert second.next_wake_at == _utc("2026-09-21T08:50")

    def test_paused_persona_does_nothing(self):
        d = engine.decide(_snap(_utc("2026-09-21T08:05"), [_w("read", "08:00", "09:00")],
                                status=E.PersonaStatus.PAUSED))
        assert d.reason == E.DecisionReason.PERSONA_PAUSED and d.results == []

    def test_world_event_deferred_during_work(self):
        """§25 u 11:48 — relevantan događaj, ali persona radi → store + defer."""
        d = engine.decide(_snap(_utc("2026-09-21T11:48"), [_w("work", "09:30", "12:30")],
                                reason=E.WakePriority.WORLD_EVENT_HIGH,
                                event=engine.PendingEvent("EVT-x", 0.9)))
        assert (d.decision, d.reason) == (E.WakeDecision.DEFER, E.DecisionReason.EVENT_DEFERRED)


# ---------------------------------------------------------------- baza


@pytest.fixture
def mila(db):
    call_command("seed_agent_001", stdout=io.StringIO())
    p = Persona.objects.get(public_id="P-00001")
    Persona.objects.filter(pk=p.pk).update(status=E.PersonaStatus.ACTIVE)
    p.refresh_from_db()
    return p


@requires_db
@pytest.mark.django_db
class TestService:
    def test_wake_records_decision_and_versioned_deltas(self, mila):
        v0 = BehaviourState.objects.get(persona=mila).state_version
        run = service.wake(mila, E.WakePriority.ROUTINE_WINDOW, now=_utc("2026-09-21T08:05"),
                           seed=20260914)
        assert run.decision in E.WakeDecision.values() and run.reason_code
        deltas = list(StateDelta.objects.filter(run=run).order_by("from_version"))
        assert deltas and deltas[0].from_version == v0
        assert all(b.from_version == a.to_version for a, b in zip(deltas, deltas[1:], strict=False))
        st = BehaviourState.objects.get(persona=mila)
        assert st.state_version == deltas[-1].to_version
        assert st.next_wake_at > _utc("2026-09-21T08:05")

    def test_act_creates_plan_never_action(self, mila):
        run = service.wake(mila, E.WakePriority.OPERATOR_TASK, now=_utc("2026-09-21T09:40"))
        assert run.decision == E.WakeDecision.ACT
        assert AgentPlan.objects.filter(run=run).count() == 1
        assert not Action.objects.exists()
        types = set(EventOutbox.objects.values_list("event_type", flat=True))
        assert {"persona.woken", "behaviour.state.recomputed", "plan.created"} <= types

    def test_wake_key_is_idempotent(self, mila):
        a = service.wake(mila, E.WakePriority.ROUTINE_WINDOW,
                         now=_utc("2026-09-21T08:05"), wake_key="k-1")
        b = service.wake(mila, E.WakePriority.ROUTINE_WINDOW,
                         now=_utc("2026-09-21T08:05"), wake_key="k-1")
        assert a.pk == b.pk and AgentRun.objects.count() == 1

    def test_seven_days_same_seed_same_story(self, mila):
        def story():
            out = io.StringIO()
            call_command("simulate", persona="P-00001", days=7, start="2026-09-21",
                         seed=20260914, golden=True, stdout=out)
            return out.getvalue()
        first, second = story(), story()
        assert first == second
        assert "EVENT_DEFERRED" in first and "REST_WINDOW" in first
        assert not AgentRun.objects.exists()  # bez --commit sve se poništava


@requires_db
@pytest.mark.django_db(transaction=True)
def test_parallel_wake_same_key_single_run():
    call_command("seed_agent_001", stdout=io.StringIO())
    p = Persona.objects.get(public_id="P-00001")
    barrier, errors = threading.Barrier(6), []

    def worker():
        try:
            barrier.wait()
            service.wake(p, E.WakePriority.ROUTINE_WINDOW,
                         now=_utc("2026-09-21T08:05"), wake_key="parallel-1")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert AgentRun.objects.filter(wake_key="parallel-1").count() == 1


@requires_db
@pytest.mark.django_db(transaction=True)
def test_concurrent_scans_never_pick_same_persona():
    """§28: mnogo due redova + SKIP LOCKED → bez duplikata."""
    call_command("seed_agent_001", stdout=io.StringIO())
    src = Persona.objects.get(public_id="P-00001")
    src_state = BehaviourState.objects.get(persona=src)
    now = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    for n in range(2, 202):
        p = Persona.objects.create(
            public_id=f"P-{n:05d}", slug=f"p-{n}", display_name=f"P{n} (AI)",
            persona_type=src.persona_type, status=E.PersonaStatus.ACTIVE,
            runtime_environment=src.runtime_environment, trust_level=src.trust_level,
            disclosure_mode=src.disclosure_mode, disclosure_required=True,
            primary_locale=src.primary_locale, timezone=src.timezone,
        )
        fields = {f.name: getattr(src_state, f.name) for f in BehaviourState._meta.fields
                  if f.name not in ("persona", "updated_at")}
        BehaviourState.objects.create(persona=p, **(fields | {"next_wake_at": now}))

    picked: list[list[str]] = []

    def worker():
        try:
            picked.append([d.persona_public_id for d in scheduler.scan_due(now, limit=80)])
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    flat = [x for batch in picked for x in batch]
    assert len(flat) == len(set(flat))
    assert "P-00001" not in flat  # READY se ne budi automatski
    assert len(flat) == 200
    again = scheduler.scan_due(now, limit=500)
    assert not {d.persona_public_id for d in again} & set(flat)  # uzeti su „claim"-ovani


@requires_db
@pytest.mark.django_db
class TestWorld:
    def test_dedupe(self, mila):
        kw = dict(event_type="industry.news", topics=["ai"], geo=["RS"], source="t",
                  dedupe_key="same-1", now=_utc("2026-09-21T10:00"))
        ev, _ = world.ingest(**kw)
        again, routes = world.ingest(**kw)
        assert ev is not None and again is None and routes == []

    def test_relevance_thresholds(self, mila):
        now = _utc("2026-09-21T10:00")
        _, hot = world.ingest(event_type="industry.news", topics=["ai"], geo=["RS"],
                              source="t", dedupe_key="hot", now=now)
        _, cold = world.ingest(event_type="industry.news", topics=["gardening"], geo=["US"],
                               occurred_at=now - timedelta(days=3), source="t",
                               dedupe_key="cold", now=now)
        assert hot[0].outcome == "wake" and hot[0].relevance >= E.WORLD_RELEVANCE_WAKE_FROM
        assert cold[0].outcome == "ignore"


# ---------------------------------------------------------------- API


@requires_db
@pytest.mark.django_db
class TestBehaviourApi:
    def _client(self, username, role):
        from django.contrib.auth.models import Group, User
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient

        u = User.objects.create_user(username=username)
        u.groups.add(Group.objects.get_or_create(name=role.value)[0])
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}")
        return c

    def _h(self, actor, key):
        return {"HTTP_X_REQUEST_ID": f"req-{key}", "HTTP_X_ACTOR_ID": actor,
                "HTTP_TRACEPARENT": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
                "HTTP_IDEMPOTENCY_KEY": key}

    def test_operator_wake_returns_run(self, mila):
        c = self._client("ops", E.Role.OPERATOR)
        r = c.post("/api/v1/personas/P-00001/wake", format="json",
                   **self._h("user:ops", "wake-001"))
        assert r.status_code == 202, r.content
        run_id = r.json()["data"]["run_id"]
        assert r["Location"] == f"/api/v1/runs/{run_id}"
        run = c.get(f"/api/v1/runs/{run_id}").json()["data"]
        assert run["decision"] in E.WakeDecision.values()
        assert run["trace_id"] == "0af7651916cd43dd8448eb211c80319c"

    def test_viewer_cannot_wake(self, mila):
        c = self._client("v", E.Role.VIEWER)
        r = c.post("/api/v1/personas/P-00001/wake", format="json", **self._h("user:v", "wake-002"))
        assert r.status_code == 403 and not AgentRun.objects.exists()

    def test_draft_persona_is_not_woken(self, mila):
        Persona.objects.filter(pk=mila.pk).update(status=E.PersonaStatus.DRAFT)
        c = self._client("ops", E.Role.OPERATOR)
        r = c.post("/api/v1/personas/P-00001/behaviour/tick", format="json",
                   **self._h("user:ops", "tick-001"))
        assert r.status_code == 400 and not AgentRun.objects.exists()

    def test_timeline_lists_skips_too(self, mila):
        for i, t in enumerate(["08:05", "12:35", "21:05"]):
            service.wake(mila, E.WakePriority.ROUTINE_WINDOW, now=_utc(f"2026-09-21T{t}"),
                         wake_key=f"tl-{i}")
        c = self._client("v2", E.Role.VIEWER)
        body = c.get("/api/v1/ops/personas/P-00001/timeline").json()
        assert len(body["data"]) == 3
        assert "REST_WINDOW" in {r["reason_code"] for r in body["data"]}
        skips = c.get("/api/v1/ops/personas/P-00001/timeline", {"decision": "SKIP"}).json()["data"]
        assert skips and all(r["decision"] == "SKIP" for r in skips)
