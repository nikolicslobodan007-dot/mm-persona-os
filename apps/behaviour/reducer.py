"""Deterministički reducer stanja. Canon §4.3, Behaviour v0.1 §5.

    new_state, changes = reduce(state, event, context)

Čista funkcija: bez baze, bez sata, bez slučajnosti. Isti ulaz → isti
izlaz, pa se svaki `StateDelta` može ponovo izračunati i proveriti. LLM
nikada ne menja stanje direktno (Canon §4.3) — on predlaže, reducer
menja na osnovu ishoda.

Stanje je `dict[str, Decimal]` sa kanonskim poljima iz §4.2 plus `ext`
(`BehaviourState.state_ext`). Sve vrednosti se seku na svoj opseg posle
svake promene; CHECK ograničenja u bazi su druga linija odbrane, ne prva.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from common import enums as E

D = Decimal
_Q3 = D("0.001")
_Q2 = D("0.01")

#: Canon §4.2 — polja u opsegu 0..1.
UNIT_FIELDS: tuple[str, ...] = (
    "energy", "arousal", "cognitive_load", "social_appetite", "curiosity_now",
    "focus", "novelty_need", "stress", "content_pressure", "inbox_pressure",
    "topic_saturation", "risk_alert",
)
STATE_FIELDS: tuple[str, ...] = (*UNIT_FIELDS, "valence", "attention_remaining")

#: Tačka ka kojoj se stanje vraća dok se ništa ne dešava (po satu).
RESTING = {"stress": D("0.150"), "arousal": D("0.400"), "curiosity_now": D("0.700")}
MAX_ELAPSED_HOURS = 16

#: Behaviour v0.1 §5 — efekat završene aktivnosti. Brojevi su namerno mali:
#: jedan dan ne sme da promeni personu preko noći.
ACTIVITY_EFFECTS: dict[E.ActivityKind, dict[str, str]] = {
    E.ActivityKind.READ: {"energy": "-0.030", "curiosity_now": "-0.050",
                          "cognitive_load": "0.050", "focus": "-0.020",
                          "topic_saturation": "0.030"},
    E.ActivityKind.RESEARCH: {"energy": "-0.080", "curiosity_now": "-0.100",
                              "cognitive_load": "0.100", "focus": "-0.050",
                              "topic_saturation": "0.050"},
    E.ActivityKind.WORK: {"energy": "-0.120", "focus": "-0.080",
                          "cognitive_load": "-0.100", "stress": "0.020"},
    E.ActivityKind.POST: {"energy": "-0.060", "content_pressure": "-0.200",
                          "cognitive_load": "0.050", "valence": "0.020"},
    E.ActivityKind.SOCIAL: {"energy": "-0.040", "social_appetite": "-0.150",
                            "valence": "0.040"},
    E.ActivityKind.INBOX: {"energy": "-0.020", "inbox_pressure": "-0.300",
                           "cognitive_load": "0.030"},
    E.ActivityKind.REST: {},
}


@dataclass
class Result:
    state: dict[str, Any]
    changes: dict[str, list[str]] = field(default_factory=dict)


def _clamp(name: str, v: Decimal) -> Decimal:
    if name == "valence":
        return max(D(-1), min(D(1), v)).quantize(_Q3, ROUND_HALF_EVEN)
    if name == "attention_remaining":
        return max(D(0), min(D(24), v)).quantize(_Q2, ROUND_HALF_EVEN)
    return max(D(0), min(D(1), v)).quantize(_Q3, ROUND_HALF_EVEN)


def _toward(cur: Decimal, target: Decimal, step: Decimal) -> Decimal:
    if cur > target:
        return max(target, cur - step)
    return min(target, cur + step)


def _day(ext: dict) -> dict:
    return ext.setdefault("day", {"date": None, "counts": {}, "last_at": {}, "windows": {}})


# ---------------------------------------------------------------- pravila


def _time_elapsed(s: dict, ctx: dict) -> None:
    hours = min(D(str(ctx["minutes"])) / 60, D(MAX_ELAPSED_HOURS))
    if hours <= 0:
        return
    s["energy"] -= D("0.010") * hours
    s["cognitive_load"] -= D("0.030") * hours
    for f, target in RESTING.items():
        s[f] = _toward(s[f], target, D("0.020") * hours)


def _day_started(s: dict, ctx: dict) -> None:
    s["energy"] += D("0.350")
    s["stress"] -= D("0.150")
    s["cognitive_load"] = s["cognitive_load"] * D("0.3")
    s["topic_saturation"] = s["topic_saturation"] * D("0.5")
    s["content_pressure"] += D("0.100")
    s["inbox_pressure"] += D("0.050")
    s["attention_remaining"] = D(str(ctx["attention_daily"]))
    s["ext"]["day"] = {"date": ctx["local_date"], "counts": {}, "last_at": {}, "windows": {}}


def _activity_completed(s: dict, ctx: dict) -> None:
    kind = E.ActivityKind(ctx["kind"])
    for f, d in ACTIVITY_EFFECTS[kind].items():
        s[f] += D(d)
    s["attention_remaining"] -= D(E.ACTIVITY_ATTENTION_COST[kind])
    day = _day(s["ext"])
    day["counts"][kind.value] = day["counts"].get(kind.value, 0) + 1
    day["last_at"][kind.value] = ctx["at"]
    if ctx.get("window_id"):
        day["windows"][ctx["window_id"]] = E.WakeDecision.ACT.value


def _window_closed(s: dict, ctx: dict) -> None:
    _day(s["ext"])["windows"][ctx["window_id"]] = ctx["decision"]


def _world_event_relevant(s: dict, ctx: dict) -> None:
    r = D(str(ctx["relevance"]))
    s["curiosity_now"] += D("0.050") * r
    s["arousal"] += D("0.030") * r
    s["novelty_need"] -= D("0.020")


RULES: dict[str, Callable[[dict, dict], None]] = {
    "time.elapsed": _time_elapsed,
    "day.started": _day_started,
    "activity.completed": _activity_completed,
    "window.closed": _window_closed,
    "world.event.relevant": _world_event_relevant,
}


def reduce(state: dict[str, Any], event: str, context: dict[str, Any]) -> Result:
    """Primeni jedno pravilo. Ulaz se ne menja; vraća se novo stanje i razlike."""
    if event not in RULES:
        raise KeyError(f"nepoznato pravilo reducera: {event!r}")
    new = {k: (D(str(v)) if k in STATE_FIELDS else v) for k, v in state.items() if k != "ext"}
    new["ext"] = copy.deepcopy(state.get("ext") or {})
    RULES[event](new, context)
    for f in STATE_FIELDS:
        new[f] = _clamp(f, new[f])

    changes: dict[str, list[str]] = {}
    for f in STATE_FIELDS:
        before = _clamp(f, D(str(state[f])))
        if new[f] != before:
            changes[f] = [str(before), str(new[f])]
    if new["ext"] != (state.get("ext") or {}):
        changes["ext.day"] = [
            str((state.get("ext") or {}).get("day", {}).get("date")),
            str(new["ext"].get("day", {}).get("date")),
        ]
    return Result(new, changes)
