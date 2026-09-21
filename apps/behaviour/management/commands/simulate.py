"""Simulacija dana persone na simuliranom satu. Behaviour v0.1 §24–§25, §30.

    python manage.py simulate --persona P-00001 --days 7 --seed 20260914
    python manage.py simulate --persona P-00001 --days 1 --golden

Isti engine, isti reducer, ista baza — samo sat ide skokovima od buđenja
do buđenja. Podrazumevano se sve poništava na kraju (`--commit` čuva), jer
simulirani dani leže u budućnosti i ne smeju da ostanu u stanju prave
persone. Spoljnih akcija nema ni u jednom režimu.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.context import bind
from apps.behaviour import service, world
from apps.behaviour.clock import SimClock, local
from apps.behaviour.models import BehaviourState
from apps.personas.models import Persona
from common import enums as E

MAX_WAKES_PER_DAY = 48


class Command(BaseCommand):
    help = "Simuliraj N dana jedne persone i ispiši svaku odluku."

    def add_arguments(self, parser):
        parser.add_argument("--persona", required=True)
        parser.add_argument("--days", type=int, default=1)
        parser.add_argument("--seed", type=int, default=20260914)
        parser.add_argument("--start", default=None,
                            help="Lokalni datum početka YYYY-MM-DD (podrazumevano sutra).")
        parser.add_argument("--golden", action="store_true",
                            help="Ubaci relevantan industrijski događaj u 11:48 prvog dana (§25).")
        parser.add_argument("--commit", action="store_true", help="Sačuvaj rezultat u bazi.")

    def handle(self, *args, persona, days, seed, start, golden, commit, **opts):
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"{persona} ne postoji.")
        tz = ZoneInfo(p.timezone)
        first = (datetime.fromisoformat(start).date() if start
                 else (datetime.now(tz) + timedelta(days=1)).date())
        clock = SimClock(datetime.combine(first, time(0, 0), tzinfo=tz).astimezone(ZoneInfo("UTC")))
        end = clock.now + timedelta(days=days)
        golden_at = (datetime.combine(first, time(11, 48), tzinfo=tz).astimezone(ZoneInfo("UTC"))
                     if golden else None)

        counts = {d.value: 0 for d in E.WakeDecision}
        with bind(actor_id="service:simulation"), transaction.atomic():
            BehaviourState.objects.filter(persona=p).update(next_wake_at=clock.now)
            wakes = 0
            while wakes < MAX_WAKES_PER_DAY * days:
                st = BehaviourState.objects.get(persona=p)
                nxt = st.next_wake_at
                if golden_at and (nxt is None or golden_at <= nxt):
                    clock.now = golden_at
                    ev, routes = world.ingest(
                        event_type="industry.news", topics=["ai", "logistics"], geo=["RS"],
                        occurred_at=golden_at - timedelta(minutes=10), source="simulation",
                        dedupe_key=f"sim-golden-{seed}-{first}", now=golden_at,
                        statuses=E.WAKEABLE_BY_OPERATOR,
                    )
                    golden_at = None
                    for r in world.pending_wakes(routes):
                        if r.persona_public_id == p.public_id:
                            run = service.wake(p, E.WakePriority.WORLD_EVENT_HIGH, now=clock.now,
                                               event=ev, relevance=r.relevance, seed=seed)
                            self._line(p, run, counts)
                            wakes += 1
                    continue
                if nxt is None or nxt >= end:
                    break
                clock.now = max(clock.now, nxt)
                run = service.wake(p, E.WakePriority.ROUTINE_WINDOW, now=clock.now, seed=seed)
                self._line(p, run, counts)
                wakes += 1
            st = BehaviourState.objects.get(persona=p)
            self.stdout.write(
                f"\n{wakes} buđenja · " + " · ".join(f"{k} {v}" for k, v in counts.items())
                + f" · energija {st.energy} · pažnja {st.attention_remaining}"
                + f" · stanje v{st.state_version}"
            )
            if not commit:
                transaction.set_rollback(True)
                self.stdout.write("Poništeno (bez --commit). Stanje persone je nepromenjeno.")

    def _line(self, p, run, counts):
        counts[run.decision] += 1
        s = run.summary_json or {}
        when = local(run.started_at, p.timezone).strftime("%a %d.%m %H:%M")
        what = s.get("activity") or (s.get("window") or {}).get("kind") or "—"
        self.stdout.write(f"{when}  {run.decision:<5} {run.reason_code:<22} {what}")
