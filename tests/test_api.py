"""F2 — API, header-i, greške, idempotentnost, RBAC, event bus, audit.

Canon §7, §8, §15, §16.5. Svaki test ovde odgovara jednoj rečenici iz
Canon-a; ako test padne, pogrešan je kod ili Canon — ne test.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from django.contrib.auth.models import Group, User
from django.db import connection, transaction
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api import audit
from api.context import bind
from apps.observability import bus
from apps.observability.models import AuditEvent, EventDelivery, EventOutbox, IdempotencyRecord
from apps.personas.models import Persona
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

TRACE = "0af7651916cd43dd8448eb211c80319c"
TRACEPARENT = f"00-{TRACE}-b7ad6b7169203331-01"


# ---------------------------------------------------------------- pomoćno


def _user(username: str, *roles: E.Role) -> User:
    u = User.objects.create_user(username=username, password=None)
    for r in roles:
        g, _ = Group.objects.get_or_create(name=r.value)
        u.groups.add(g)
    return u


def _client(user: User | None) -> APIClient:
    c = APIClient()
    if user is not None:
        token, _ = Token.objects.get_or_create(user=user)
        c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return c


def _write_headers(actor: str, *, key: str | None = None, **extra) -> dict:
    h = {
        "HTTP_X_REQUEST_ID": f"req-{uuid.uuid4().hex[:12]}",
        "HTTP_TRACEPARENT": TRACEPARENT,
        "HTTP_X_ACTOR_ID": actor,
    }
    if key:
        h["HTTP_IDEMPOTENCY_KEY"] = key
    h.update(extra)
    return h


def _new_persona_body(**over) -> dict:
    body = {
        "display_name": "Test Persona (AI)",
        "persona_type": E.PersonaType.AI_CREATOR.value,
        "disclosure_mode": E.DisclosureMode.ALWAYS_VISIBLE.value,
        "primary_locale": "sr-Latn-RS",
        "timezone": "Europe/Belgrade",
    }
    body.update(over)
    return body


@pytest.fixture
def manager(db):
    return _user("marko", E.Role.PERSONA_MANAGER)


@pytest.fixture
def viewer(db):
    return _user("vera", E.Role.VIEWER)


@pytest.fixture
def persona(db, manager):
    c = _client(manager)
    r = c.post("/api/v1/personas", _new_persona_body(), format="json",
               **_write_headers("user:marko", key="create-fixture-1"))
    assert r.status_code == 201, r.content
    return Persona.objects.get(public_id=r.json()["data"]["public_id"])


# ---------------------------------------------------------------- header-i


@pytest.mark.django_db
class TestHeaders:
    def test_write_without_headers_is_rejected(self, manager):
        r = _client(manager).post("/api/v1/personas", _new_persona_body(), format="json")
        assert r.status_code == 400
        err = r.json()["error"]
        assert err["code"] == E.ErrorCode.VALIDATION_ERROR.value
        assert set(err["details"]["headers"]) == {"X-Request-ID", "traceparent", "X-Actor-ID"}
        assert not Persona.objects.exists()

    def test_read_without_headers_gets_generated_ids(self, manager):
        r = _client(manager).get("/api/v1/personas")
        assert r.status_code == 200
        assert r["X-Request-ID"].startswith("req_")
        assert len(r["X-Trace-ID"]) == 32

    def test_malformed_traceparent_rejected_even_on_read(self, manager):
        r = _client(manager).get("/api/v1/personas", HTTP_TRACEPARENT="nije-trace")
        assert r.status_code == 400
        assert "traceparent" in r.json()["error"]["details"]["headers"]

    def test_trace_id_flows_from_traceparent(self, manager):
        r = _client(manager).get("/api/v1/personas", HTTP_TRACEPARENT=TRACEPARENT)
        assert r["X-Trace-ID"] == TRACE
        assert r.json()["meta"]["trace_id"] == TRACE

    def test_human_cannot_declare_someone_else(self, manager):
        r = _client(manager).post(
            "/api/v1/personas", _new_persona_body(), format="json",
            **_write_headers("user:neko-drugi", key="spoof-attempt-1"),
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == E.ErrorCode.FORBIDDEN.value

    def test_healthz_is_outside_contract(self, db):
        r = APIClient().get("/healthz")
        assert r.status_code == 200
        assert r.json()["db"] == "ok"


# ---------------------------------------------------------------- greške


@pytest.mark.django_db
class TestErrorEnvelope:
    def test_unauthenticated(self, db):
        r = APIClient().get("/api/v1/personas")
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == E.ErrorCode.UNAUTHENTICATED.value
        assert set(body["error"]) == {"code", "message", "details", "retryable"}
        assert set(body["meta"]) == {"request_id", "trace_id"}

    def test_not_found_uses_canon_code(self, manager):
        r = _client(manager).get("/api/v1/personas/P-99999")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == E.ErrorCode.NOT_FOUND.value

    def test_malformed_id_is_not_found_not_500(self, manager):
        assert _client(manager).get("/api/v1/personas/nesto").status_code == 404
        assert _client(manager).get("/api/v1/actions/ACT-xyz").status_code == 404

    def test_every_status_comes_from_canon_table(self):
        assert E.ERROR_HTTP_STATUS[E.ErrorCode.VERSION_CONFLICT] == 409
        assert E.ERROR_HTTP_STATUS[E.ErrorCode.IDEMPOTENCY_CONFLICT] == 409


# ---------------------------------------------------------------- persone


@pytest.mark.django_db
class TestPersonas:
    def test_create_is_draft_simulation_l0(self, persona):
        assert persona.status == E.PersonaStatus.DRAFT
        assert persona.runtime_environment == E.RuntimeEnvironment.SIMULATION
        assert persona.trust_level == E.TrustLevel.L0

    def test_create_requires_ai_marker(self, manager):
        r = _client(manager).post(
            "/api/v1/personas", _new_persona_body(display_name="Bez Oznake"), format="json",
            **_write_headers("user:marko", key="no-marker-01"),
        )
        assert r.status_code == 400
        assert not Persona.objects.exists()

    def test_create_requires_idempotency_key(self, manager):
        r = _client(manager).post("/api/v1/personas", _new_persona_body(), format="json",
                                  **_write_headers("user:marko"))
        assert r.status_code == 400
        assert "Idempotency-Key" in r.json()["error"]["details"]["headers"]

    def test_create_writes_audit_with_hash(self, persona):
        row = AuditEvent.objects.get(event_key="api.persona.created")
        assert row.persona_id == persona.pk
        assert row.trace_id.hex == TRACE
        assert row.actor_ref == "user:marko"
        assert len(row.payload["after_hash"]) == 64
        assert len(row.payload_hash) == 64

    def test_get_returns_etag(self, manager, persona):
        r = _client(manager).get(f"/api/v1/personas/{persona.public_id}")
        assert r["ETag"] == f'"v{persona.version}"'

    def test_patch_without_if_match_rejected(self, manager, persona):
        r = _client(manager).patch(
            f"/api/v1/personas/{persona.public_id}", {"primary_locale": "en-US"},
            format="json", **_write_headers("user:marko"),
        )
        assert r.status_code == 400

    def test_patch_stale_version_conflicts(self, manager, persona):
        c = _client(manager)
        url = f"/api/v1/personas/{persona.public_id}"
        v = persona.version
        ok = c.patch(url, {"primary_locale": "en-US"}, format="json",
                     **_write_headers("user:marko", HTTP_IF_MATCH=f'"v{v}"'))
        assert ok.status_code == 200
        assert ok["ETag"] == f'"v{v + 1}"'
        stale = c.patch(url, {"primary_locale": "de-DE"}, format="json",
                        **_write_headers("user:marko", HTTP_IF_MATCH=f'"v{v}"'))
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == E.ErrorCode.VERSION_CONFLICT.value
        assert stale["ETag"] == f'"v{v + 1}"'
        persona.refresh_from_db()
        assert persona.primary_locale == "en-US"

    def test_patch_rejects_unknown_fields(self, manager, persona):
        r = _client(manager).patch(
            f"/api/v1/personas/{persona.public_id}", {"trust_level": "L4"}, format="json",
            **_write_headers("user:marko", HTTP_IF_MATCH=f'"v{persona.version}"'),
        )
        assert r.status_code == 400
        persona.refresh_from_db()
        assert persona.trust_level == E.TrustLevel.L0

    def test_snapshot(self, manager, persona):
        r = _client(manager).get(f"/api/v1/personas/{persona.public_id}/snapshot")
        assert r.status_code == 200
        assert r.json()["data"]["persona"]["public_id"] == persona.public_id


# ---------------------------------------------------------------- RBAC


@pytest.mark.django_db
class TestRBAC:
    def test_viewer_can_read_personas(self, viewer):
        assert _client(viewer).get("/api/v1/personas").status_code == 200

    def test_viewer_cannot_create(self, viewer):
        r = _client(viewer).post("/api/v1/personas", _new_persona_body(), format="json",
                                 **_write_headers("user:vera", key="viewer-try-1"))
        assert r.status_code == 403
        assert not Persona.objects.exists()

    def test_viewer_cannot_read_audit(self, viewer):
        assert _client(viewer).get("/api/v1/audit").status_code == 403

    def test_manager_reads_audit_filtered(self, manager, persona):
        r = _client(manager).get("/api/v1/audit", {"trace_id": TRACE})
        assert r.status_code == 200
        assert [e["event_key"] for e in r.json()["data"]] == ["api.persona.created"]

    def test_bootstrap_roles_is_idempotent(self, db):
        from django.core.management import call_command

        call_command("bootstrap_roles")
        call_command("bootstrap_roles")
        assert Group.objects.filter(name__in=E.Role.values()).count() == 6
        deciders = Group.objects.filter(permissions__codename="decide_approval")
        assert {g.name for g in deciders} == {r.value for r in E.APPROVAL_DECIDERS}


# ---------------------------------------------------------------- idempotentnost


@pytest.mark.django_db
class TestIdempotency:
    def test_same_key_same_body_replays(self, manager):
        c = _client(manager)
        a = c.post("/api/v1/personas", _new_persona_body(), format="json",
                   **_write_headers("user:marko", key="same-key-001"))
        b = c.post("/api/v1/personas", _new_persona_body(), format="json",
                   **_write_headers("user:marko", key="same-key-001"))
        assert a.status_code == b.status_code == 201
        assert b["Idempotent-Replayed"] == "true"
        assert b["ETag"] == a["ETag"] and b["Location"] == a["Location"]
        assert a.json()["data"]["public_id"] == b.json()["data"]["public_id"]
        assert Persona.objects.count() == 1

    def test_same_key_other_body_conflicts(self, manager):
        c = _client(manager)
        c.post("/api/v1/personas", _new_persona_body(), format="json",
               **_write_headers("user:marko", key="same-key-002"))
        r = c.post("/api/v1/personas", _new_persona_body(display_name="Druga (AI)"),
                   format="json", **_write_headers("user:marko", key="same-key-002"))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == E.ErrorCode.IDEMPOTENCY_CONFLICT.value
        assert Persona.objects.count() == 1

    def test_failed_request_does_not_burn_key(self, manager):
        c = _client(manager)
        bad = c.post("/api/v1/personas", _new_persona_body(display_name="Bez Oznake"),
                     format="json", **_write_headers("user:marko", key="retry-key-01"))
        assert bad.status_code == 400
        assert not IdempotencyRecord.objects.filter(key="retry-key-01").exists()


@pytest.mark.django_db(transaction=True)
def test_parallel_same_key_single_effect():
    """Canon §16.5: isti ključ, paralelno → tačno jedan efekat."""
    user = _user("paralela", E.Role.PERSONA_MANAGER)
    token = Token.objects.create(user=user).key
    results: list[int] = []
    barrier = threading.Barrier(8)

    def worker():
        try:
            c = APIClient()
            c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
            barrier.wait()
            r = c.post("/api/v1/personas", _new_persona_body(), format="json",
                       **_write_headers("user:paralela", key="parallel-key-1"))
            results.append(r.status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == [201] * 8
    assert Persona.objects.count() == 1
    assert IdempotencyRecord.objects.filter(key="parallel-key-1").count() == 1


# ---------------------------------------------------------------- paginacija


@pytest.mark.django_db
class TestPagination:
    def test_cursor_walks_all_rows_once(self, manager):
        c = _client(manager)
        for i in range(5):
            c.post("/api/v1/personas", _new_persona_body(display_name=f"P{i} (AI)"),
                   format="json", **_write_headers("user:marko", key=f"page-key-{i:03d}"))
        seen, cursor = [], None
        while True:
            params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
            body = c.get("/api/v1/personas", params).json()
            seen += [p["public_id"] for p in body["data"]]
            cursor = body["meta"]["page"]["next_cursor"]
            if not cursor:
                break
        assert len(seen) == len(set(seen)) == 5
        assert seen == sorted(seen, reverse=True)

    @pytest.mark.parametrize("limit", ["0", "201", "abc"])
    def test_limit_bounds(self, manager, limit):
        r = _client(manager).get("/api/v1/personas", {"limit": limit})
        assert r.status_code == 400


# ---------------------------------------------------------------- event bus


def _killswitch_payload() -> dict:
    return {"scope": "GLOBAL", "target": None, "activated_by": "user:test"}


@pytest.mark.django_db(transaction=True)
class TestEventBus:
    def test_emit_outside_transaction_refused(self):
        with pytest.raises(RuntimeError):
            bus.emit("killswitch.activated", _killswitch_payload(), persona_id=None)

    def test_invalid_payload_refused_and_nothing_written(self):
        with pytest.raises(bus.EventSchemaError):
            with transaction.atomic():
                bus.emit("killswitch.activated", {"scope": "NIŠTA"}, persona_id=None)
        assert not EventOutbox.objects.exists()

    def test_unknown_event_type_refused(self):
        with pytest.raises(ValueError, match="katalog"):
            with transaction.atomic():
                bus.emit("persona.created", {}, persona_id=None)

    def test_rollback_drops_event(self):
        with pytest.raises(ZeroDivisionError):
            with transaction.atomic():
                bus.emit("killswitch.activated", _killswitch_payload(), persona_id=None)
                1 / 0  # noqa: B018
        assert not EventOutbox.objects.exists()

    def test_emit_publishes_and_audits(self):
        with bind(trace_id=TRACE, actor_id="service:test"), transaction.atomic():
            row = bus.emit("killswitch.activated", _killswitch_payload(), persona_id=None)
        row.refresh_from_db()
        assert row.status == E.OutboxStatus.PUBLISHED
        assert row.envelope["trace_id"] == TRACE
        a = AuditEvent.objects.get(event_key="event.killswitch.activated")
        assert a.trace_id.hex == TRACE

    def test_redelivery_ten_times_single_effect(self):
        """Canon §7.4: at-least-once isporuka, consumer vidi event jednom."""
        with transaction.atomic():
            row = bus.emit("killswitch.activated", _killswitch_payload(), persona_id=None)
        for _ in range(10):
            for c in bus.consumers_for("killswitch.activated"):
                bus.deliver(c, row.envelope)
        assert EventDelivery.objects.filter(event_id=row.event_id).count() == len(
            bus.consumers_for("killswitch.activated")
        )
        assert AuditEvent.objects.filter(event_key="event.killswitch.activated").count() == 1

    def test_failing_consumer_keeps_row_pending_then_dead(self, settings):
        calls = []

        @bus.consumer("test.always_fails", "killswitch.cleared")
        def _boom(envelope):
            calls.append(envelope["event_id"])
            raise ValueError("namerno")

        try:
            settings.EVENT_BUS_EAGER = False
            with transaction.atomic():
                row = bus.emit(
                    "killswitch.cleared",
                    {"scope": "GLOBAL", "target": None, "cleared_by": "user:test"},
                    persona_id=None,
                )
            for _ in range(bus.MAX_ATTEMPTS):
                bus.publish_pending()
            row.refresh_from_db()
            assert row.status == E.OutboxStatus.DEAD
            assert row.attempts == bus.MAX_ATTEMPTS
            assert "namerno" in row.last_error
            # Audit consumer je uspeo prvi put i nije ponavljan.
            assert AuditEvent.objects.filter(event_key="event.killswitch.cleared").count() == 1
        finally:
            bus.unregister("test.always_fails")


# ---------------------------------------------------------------- audit


@pytest.mark.django_db
class TestAudit:
    def test_secrets_are_scrubbed(self):
        with bind(trace_id=TRACE, actor_id="service:test"):
            row = audit.record("test.scrub", details={"password": "x", "token": "y", "ok": 1})
        hidden = "[uklonjeno]"
        assert row.payload["details"] == {"password": hidden, "token": hidden, "ok": 1}

    def test_hash_is_deterministic(self):
        assert audit.sha256_of({"b": 1, "a": 2}) == audit.sha256_of({"a": 2, "b": 1})


@pytest.mark.django_db
def test_home_page_shows_only_name_and_health(db):
    r = APIClient().get("/")
    assert r.status_code == 200
    body = r.content.decode()
    assert "MM Persona OS" in body and "P-0000" not in body
    assert r["X-Robots-Tag"] == "noindex, nofollow"
