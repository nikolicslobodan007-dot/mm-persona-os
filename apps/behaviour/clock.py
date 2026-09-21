"""Vreme i ponovljiva slučajnost. Behaviour v0.1 §9, §24; Canon §4.3.

Dve stvari koje engine nikada ne sme da uzme „iz vazduha":

  - **Vreme.** Sve funkcije engine-a primaju `now` kao argument. Produkcija
    prosleđuje `timezone.now()`, simulacija svoj sat. Domen logika ne zna
    razliku — to je ono što omogućava 7 simuliranih dana za 2 sekunde.
  - **Slučajnost.** Nema `random.random()`. Svaka „kockica" je SHA-256 od
    (seed, persona, datum, prozor), pa isti seed daje isti niz odluka, a
    dve persone sa istom rutinom ipak ne rade isto u isti minut.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings


def roll(seed: int, *parts: object) -> float:
    """Deterministički broj u [0, 1). Isti ulaz → isti izlaz, na svakoj mašini."""
    h = hashlib.sha256(("|".join([str(seed), *map(str, parts)])).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def seed_for(local_day: date) -> int:
    """Seed dana. `BEHAVIOUR_SEED` ga fiksira (simulacija, testovi); bez njega
    seed je datum — rotira svaki dan i upisuje se u svaki run (§24)."""
    fixed = getattr(settings, "BEHAVIOUR_SEED", None)
    if fixed is not None:
        return int(fixed)
    return int(local_day.strftime("%Y%m%d"))


def local(now: datetime, tz: str) -> datetime:
    return now.astimezone(ZoneInfo(tz))


@dataclass
class SimClock:
    """Sat za simulaciju: pomera se samo kad mu se kaže."""

    now: datetime

    def advance(self, **delta: float) -> datetime:
        self.now = self.now + timedelta(**delta)
        return self.now
