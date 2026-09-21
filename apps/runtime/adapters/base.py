"""Adapter — prevodi akciju u zahteve jednog kanala. ADR-0008.

Ugovor:

  preflight(x) → Outcome | None   provere bez mreže; važe i u dry-run-u
  perform(x)   → Outcome          zahtevi idu SAMO kroz `x.send()`
  verify(x)    → ReconcileStatus  da li je efekat nastao (posle UNKNOWN_EFFECT)

`x.send()` pre svakog zahteva proverava kill-switch i rok (`CancelToken`),
beleži redigovan zahtev i zna da li je otišao zahtev koji menja stanje —
od toga zavisi da li je prekid `ABORTED_SAFE` ili `UNKNOWN_EFFECT`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from apps.channels.models import ChannelAccount
from apps.orchestration.models import Action
from apps.runtime.control import CancelToken, Stop
from apps.runtime.transport import (
    CredentialMissing,
    ExternalActionsDisabled,
    Request,
    Response,
    Transport,
    TransportError,
)
from common import enums as E

OC = E.ExecutionOutcome
R = E.RuntimeReason


@dataclass
class CostItem:
    bucket: E.CostBucket
    provider: str
    usd: Decimal
    quantity: Decimal = Decimal(1)
    unit: str = "requests"


@dataclass
class Outcome:
    outcome: E.ExecutionOutcome
    reason_code: str
    external_ref: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    evidence_level: E.EvidenceLevel = E.EvidenceLevel.RESPONSE_ONLY
    costs: list[CostItem] = field(default_factory=list)
    retry_after_s: int = 0
    detail: str = ""


class HttpStatus(Exception):
    def __init__(self, resp: Response, write: bool):
        super().__init__(str(resp.status))
        self.resp, self.write = resp, write


@dataclass
class Exec:
    action: Action
    account: ChannelAccount | None
    contract: dict[str, Any]
    transport: Transport
    token: CancelToken
    now: datetime
    sent: list[dict[str, Any]] = field(default_factory=list)
    write_sent: bool = False

    @property
    def payload(self) -> dict[str, Any]:
        return self.action.input_json or {}

    @property
    def dry(self) -> bool:
        return not self.transport.live

    def send(self, req: Request) -> Response:
        self.token.check()
        self.sent.append(req.redacted())
        if req.write:
            self.write_sent = True
        resp = self.transport.send(req, credential_ref=self.account.credential_ref
                                   if self.account else "")
        if resp.status >= 400:
            raise HttpStatus(resp, req.write)
        return resp


def text_of(payload: dict[str, Any]) -> str:
    return str(payload.get("text") or payload.get("message") or payload.get("body") or "")


_LINK = re.compile(r"https?://", re.I)


def has_link(payload: dict[str, Any]) -> bool:
    return bool(payload.get("link") or _LINK.search(text_of(payload)))


def _retry_after(resp: Response) -> int:
    try:
        return max(0, int(resp.headers.get("retry-after", "0")))
    except ValueError:
        return 0


class Adapter:
    key = "base"

    def preflight(self, x: Exec) -> Outcome | None:
        return None

    def perform(self, x: Exec) -> Outcome:  # pragma: no cover — apstraktno
        raise NotImplementedError

    def verify(self, x: Exec) -> E.ReconcileStatus:
        """Podrazumevano: ne možemo da utvrdimo — ide čoveku."""
        return E.ReconcileStatus.UNRESOLVED

    # ------------------------------------------------------------------
    def run(self, x: Exec) -> Outcome:
        try:
            x.token.check()  # kill-switch i rok pobeđuju i proveru sadržaja
            pre = self.preflight(x)
            if pre is not None:
                return pre
            return self.perform(x)
        except Stop as s:
            if x.write_sent:
                return Outcome(OC.UNKNOWN_EFFECT, s.reason.value, detail=s.detail)
            return Outcome(OC.ABORTED_SAFE, s.reason.value, detail=s.detail)
        except HttpStatus as h:
            return classify_http(h.resp, h.write)
        except TransportError as t:
            if x.write_sent:
                return Outcome(OC.UNKNOWN_EFFECT, t.reason, detail=t.detail[:500])
            return Outcome(OC.RETRYABLE_ERROR, t.reason, detail=t.detail[:500])
        except CredentialMissing as c:
            return Outcome(OC.NEEDS_AUTH, R.CREDENTIAL_MISSING.value, detail=str(c))
        except ExternalActionsDisabled as d:
            # Druga brava je uhvatila ugovor bez dry_run-a — nijedan bajt nije otišao.
            return Outcome(OC.DENIED_BY_POLICY, "EXTERNAL_ACTIONS_DISABLED", detail=str(d))


def classify_http(resp: Response, write: bool) -> Outcome:
    s = resp.status
    detail = (resp.text or "")[:500]
    if s == 429:
        return Outcome(OC.RETRYABLE_ERROR, R.HTTP_429.value, retry_after_s=_retry_after(resp),
                       detail=detail)
    if s in (401, 403):
        if (resp.json or {}).get("challenge"):
            return Outcome(OC.NEEDS_HUMAN, "CHALLENGE", detail="CAPTCHA/izazov — ne rešava se")
        return Outcome(OC.NEEDS_AUTH, R.AUTH_FAILED.value, detail=detail)
    if s >= 500:
        if write:
            return Outcome(OC.UNKNOWN_EFFECT, R.HTTP_5XX.value, detail=detail)
        return Outcome(OC.RETRYABLE_ERROR, R.HTTP_5XX.value, retry_after_s=_retry_after(resp),
                       detail=detail)
    return Outcome(OC.PERMANENT_ERROR, R.HTTP_4XX.value, detail=detail)
