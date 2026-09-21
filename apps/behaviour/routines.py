"""Rutinski prozori u lokalnom vremenu persone. Behaviour v0.1 §6, §9.

Jedino mesto u sistemu gde postoji lokalno vreme (Canon §7.1). Sve što
izlazi odavde je UTC. Prelazak na letnje i zimsko računanje vremena rešava
IANA baza (`zoneinfo`), nikad ručni pomak — 08:00 u Beogradu je 06:00 UTC
leti i 07:00 UTC zimi, i oba dana prelaza se testiraju.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from common import enums as E

#: Koliko dana unapred tražimo sledeći prozor. Nedelja + dan zaštite.
LOOKAHEAD_DAYS = 8


@dataclass(frozen=True)
class Window:
    id: str
    template: str
    day_mask: int
    template_priority: int
    kind: E.ActivityKind
    start: time
    end: time
    probability: Decimal
    constraints: dict = field(default_factory=dict, hash=False, compare=False)

    def applies_on(self, d: date) -> bool:
        return bool(self.day_mask & (1 << d.weekday()))

    def bounds_utc(self, d: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
        start = datetime.combine(d, self.start, tzinfo=tz)
        end = datetime.combine(d, self.end, tzinfo=tz)
        return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


def _ordered(windows: list[Window]) -> list[Window]:
    return sorted(windows, key=lambda w: (-w.template_priority, w.start, w.id))


def current_window(windows: list[Window], tz: str, now: datetime) -> tuple[Window, date] | None:
    """Prozor koji sadrži `now`, po lokalnom kalendaru persone."""
    z = ZoneInfo(tz)
    local_day = now.astimezone(z).date()
    for w in _ordered(windows):
        if not w.applies_on(local_day):
            continue
        start, end = w.bounds_utc(local_day, z)
        if start <= now < end:
            return w, local_day
    return None


def next_window_start(
    windows: list[Window], tz: str, now: datetime
) -> tuple[datetime, Window] | None:
    """Prvi početak prozora STROGO posle `now`."""
    z = ZoneInfo(tz)
    today = now.astimezone(z).date()
    best: tuple[datetime, Window] | None = None
    for offset in range(LOOKAHEAD_DAYS):
        d = today + timedelta(days=offset)
        for w in _ordered(windows):
            if not w.applies_on(d):
                continue
            start, _ = w.bounds_utc(d, z)
            if start > now and (best is None or start < best[0]):
                best = (start, w)
        if best is not None:
            return best
    return None


def window_end(w: Window, local_day: date, tz: str) -> datetime:
    return w.bounds_utc(local_day, ZoneInfo(tz))[1]
