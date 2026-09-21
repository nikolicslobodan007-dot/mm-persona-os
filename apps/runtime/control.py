"""Zaustavljanje u letu. Canon §9.6, §12.3, §12.6 · ADR-0008.

Adapter pre SVAKOG zahteva poziva `token.check()`. Tu se proverava:

  - kill-switch u opsegu akcije (čita se iz baze, važi za sve worker-e);
  - rok izvršenja (`deadline_at`) i gornja granica trajanja pokušaja;
  - otkucaj (heartbeat) sesije na 20 s, koji produžava lease na 90 s.

Zahtev koji je već otišao ne može se povući. Zato je granica zaustavljanja
između dva zahteva: ako je stop stigao pre prvog zahteva koji menja stanje,
ishod je `ABORTED_SAFE`; ako posle, `UNKNOWN_EFFECT` i reconcile.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from django.utils import timezone

from apps.orchestration.models import Action
from apps.policy import config as policy_config
from apps.policy import engine
from apps.policy.models import KillSwitch
from apps.runtime.models import RuntimeSession
from common import enums as E


class Stop(Exception):
    def __init__(self, reason: E.RuntimeReason, detail: str = ""):
        super().__init__(reason.value)
        self.reason, self.detail = reason, detail


def kill_switch_hit(action: Action) -> KillSwitch | None:
    """Prvi aktivan kill-switch čiji opseg pokriva akciju, ili None."""
    active = list(KillSwitch.objects.filter(is_active=True))
    if not active:
        return None
    caps = policy_config.action_types().get(action.action_type, [])
    acc = action.channel_account
    for ks in active:
        ctx = engine.Context(
            persona_id=action.persona.public_id,
            persona_status=E.PersonaStatus(action.persona.status),
            action_type=action.action_type, payload={}, now=timezone.now(),
            channel=engine.Channel(str(acc.id), acc.channel_type, acc.status,
                                   acc.disclosure_label_status, frozenset()) if acc else None,
            kill_switches=[(ks.scope, ks.target_ref)],
        )
        if engine._scope_hits(ctx, caps):
            return ks
    return None


class CancelToken:
    def __init__(self, action: Action, session: RuntimeSession | None, *,
                 max_duration_s: int = E.MAX_DURATION_SECONDS,
                 deadline_at: datetime | None = None, clock=time.monotonic) -> None:
        self.action, self.session = action, session
        self.deadline_at = deadline_at or action.deadline_at
        self.max_duration_s = max_duration_s
        self._clock = clock
        self._t0 = clock()
        self._last_beat = self._t0
        self.stopped_by: KillSwitch | None = None

    def elapsed_ms(self) -> int:
        return int((self._clock() - self._t0) * 1000)

    def check(self) -> None:
        ks = kill_switch_hit(self.action)
        if ks is not None:
            self.stopped_by = ks
            raise Stop(E.RuntimeReason.KILL_SWITCH, f"{ks.scope}:{ks.target_ref}")
        if self.deadline_at and timezone.now() >= self.deadline_at:
            raise Stop(E.RuntimeReason.DEADLINE_PASSED)
        if self._clock() - self._t0 > self.max_duration_s:
            raise Stop(E.RuntimeReason.TIMEOUT)
        self.beat()

    def beat(self, *, force: bool = False) -> None:
        if self.session is None:
            return
        now_m = self._clock()
        if force or now_m - self._last_beat >= E.HEARTBEAT_SECONDS:
            now = timezone.now()
            RuntimeSession.objects.filter(pk=self.session.pk,
                                          status=E.SessionStatus.OPEN.value).update(
                heartbeat_at=now, lease_expires_at=now + timedelta(seconds=E.LEASE_TTL_SECONDS))
            self._last_beat = now_m
