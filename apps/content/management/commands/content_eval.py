"""Merenje modela za nacrte na srpskom — ista pitanja, iste provere. ADR-0011.

    python manage.py content_eval --persona P-00001
    python manage.py content_eval --persona P-00001 --topics "AI u prodaji;Rokovi isporuke"

Za svaku rutu `content_draft` (lokalni šablon + svaka uključena spoljna) pravi
nacrt za svaku temu, sa ISTIM kontekstom iz memorije, i meri:

  ok        — nacrta bez greške
  zabrane   — koliko nacrta pogađa tvrdu zabranu (mora biti 0)
  latinica  — udeo latiničnih slova (persona piše sr-Latn)
  dijakr.   — udeo nacrta sa č/ć/ž/š/đ (pravi srpski, ne „ošišana latinica")
  ponavlj.  — najveća sličnost dva nacrta iste rute (manje je bolje; 0,8 = odbijeno)
  znakova   — prosečna dužina
  ms        — prosečno trajanje
  trošak    — ukupno, u centima

Nacrti se NE čuvaju kao sadržaj i ne idu na odobrenje. Ostaju samo tragovi
poziva (PromptRecord, trošak) — da se zna šta je merenje koštalo.
"""

from __future__ import annotations

import itertools
import re
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.context import bind
from apps.content.service import _system_prompt, operator_run
from apps.llm_gateway import gateway
from apps.memory import context as memory_context
from apps.personas.models import Persona
from apps.policy import guards
from apps.runtime.adapters.social import similarity
from common import enums as E

DEFAULT_TOPICS = (
    "AI u B2B prodaji",
    "Kako dobavljač gradi poverenje",
    "Rokovi isporuke i realna obećanja",
    "Šta kupac proverava pre prve narudžbine",
    "Cena naspram vrednosti u ponudi",
    "Greška koju sam videla u pregovorima",
)
_LAT = re.compile(r"[A-Za-zČĆŽŠĐčćžšđ]")
_CYR = re.compile(r"[Ѐ-ӿ]")
_DIA = re.compile(r"[čćžšđČĆŽŠĐ]")


class Command(BaseCommand):
    help = "Uporedi rute za nacrte na istim temama (ADR-0011)."

    def add_arguments(self, parser):
        parser.add_argument("--persona", default="P-00001")
        parser.add_argument("--topics", default="")

    def handle(self, *args, persona, topics, **opts):
        p = Persona.objects.filter(public_id=persona).first()
        if p is None:
            raise CommandError(f"Persona {persona} ne postoji.")
        topic_list = [t.strip() for t in topics.split(";") if t.strip()] or list(DEFAULT_TOPICS)
        routes = gateway.routes(E.LLMPurpose.CONTENT_DRAFT)
        with bind(actor_id="service:content-eval"):
            run = operator_run(p, timezone.now())
            run.summary_json = {"task": "content_eval", "topics": len(topic_list)}
            run.save(update_fields=["summary_json"])
            packs = {t: memory_context.build(p, run, E.RetrievalProfile.CONTENT_CREATION, query=t)
                     for t in topic_list}
            rows = []
            for route in routes:
                rows.append(self._measure(p, run, route, topic_list, packs))
        self.stdout.write(self._table(rows))
        self.stdout.write(f"\nRun: {run.public_id} · tema: {len(topic_list)} · "
                          f"spoljni modeli {'uključeni' if routes[:-1] else 'nisu dodati'}.")

    def _measure(self, p, run, route, topics, packs) -> dict:
        texts, errors, ms, cents = [], [], [], 0
        for t in topics:
            pack = packs[t]
            facts = [sc.memory.content if len(sc.memory.content) < 200 else sc.memory.title
                     for sc in pack.items[:2]]
            t0 = time.monotonic()
            try:
                g = gateway.generate(
                    E.LLMPurpose.CONTENT_DRAFT, _system_prompt(p),
                    f"{pack.text}\n\n## zadatak\nNapiši kratku objavu na temu: {t}.",
                    persona=p, run=run, context_pack=pack.record, only=route,
                    brief={"topic": t, "facts": facts, "language": p.primary_locale})
                texts.append(g.text)
                cents += g.amount_eur_cents
            except gateway.LLMError as e:
                errors.append(e.code)
            ms.append(int((time.monotonic() - t0) * 1000))
        letters = "".join(texts)
        lat, cyr = len(_LAT.findall(letters)), len(_CYR.findall(letters))
        pairs = [similarity(a, b) for a, b in itertools.combinations(texts, 2)]
        return {
            "ruta": f"{route.provider}/{route.model_key}",
            "ok": f"{len(texts)}/{len(topics)}",
            "zabrane": sum(1 for x in texts if guards.prohibitions(
                "channel.post.create", {"text": x}, "")),
            "latinica": f"{lat / max(1, lat + cyr):.0%}",
            "dijakr.": f"{sum(1 for x in texts if _DIA.search(x)) / max(1, len(texts)):.0%}",
            "ponavlj.": f"{max(pairs, default=0):.2f}",
            "znakova": int(sum(map(len, texts)) / max(1, len(texts))),
            "ms": int(sum(ms) / max(1, len(ms))),
            "trošak": f"{cents} c",
            "greške": ",".join(sorted(set(errors))) or "—",
        }

    @staticmethod
    def _table(rows: list[dict]) -> str:
        cols = list(rows[0])
        w = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
        line = "  ".join(c.ljust(w[c]) for c in cols)
        body = ["  ".join(str(r[c]).ljust(w[c]) for c in cols) for r in rows]
        return "\n".join([line, "-" * len(line), *body])
