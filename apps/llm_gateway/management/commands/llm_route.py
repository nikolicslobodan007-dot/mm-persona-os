"""Rute LLM Gateway-a — dodaj, uključi, isključi, prikaži. ADR-0009, ADR-0011.

    manage.py llm_route list
    manage.py llm_route add --provider anthropic --model claude-sonnet-5 \\
        --in-usd 2 --out-usd 10 --priority 10          (dodaje ISKLJUČENU rutu)
    manage.py llm_route enable  --provider anthropic --model claude-sonnet-5
    manage.py llm_route disable --provider anthropic --model claude-sonnet-5

Cene se unose u USD po milion tokena (kako ih provajder objavljuje) i
pretvaraju u EUR mikrocente po 1000 tokena po kursu iz channels/platforms.yaml.
Nova ruta je uvek isključena: prvo `content_eval`, pa odluka, pa `enable`.
Pored toga, spoljni poziv traži i LLM_EXTERNAL_ENABLED=true u .env.prod.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.core.management.base import BaseCommand, CommandError

from api import audit
from api.context import bind
from apps.llm_gateway.models import LLMRoute
from apps.runtime import config as rconfig
from common import enums as E

#: Provajderi koji po uslovima API-ja ne treniraju na poslatim podacima.
#: Anthropic: komercijalni uslovi API-ja — podaci se ne koriste za trening.
NO_TRAINING = {"anthropic"}


def _micro_eur_per_1k(usd_per_mtok: str) -> int:
    eur = Decimal(usd_per_mtok) * rconfig.fx_usd_eur()          # EUR po milion
    return int((eur * 1_000_000 / 1000).quantize(Decimal(1), ROUND_HALF_UP))


class Command(BaseCommand):
    help = "Upravljanje LLM rutama."

    def add_arguments(self, parser):
        parser.add_argument("op", choices=["list", "add", "enable", "disable"])
        parser.add_argument("--provider")
        parser.add_argument("--model")
        parser.add_argument("--purpose", default=E.LLMPurpose.CONTENT_DRAFT.value,
                            choices=E.LLMPurpose.values())
        parser.add_argument("--priority", type=int, default=10)
        parser.add_argument("--in-usd", default="0", help="USD po milion ulaznih tokena")
        parser.add_argument("--out-usd", default="0", help="USD po milion izlaznih tokena")
        parser.add_argument("--max-output", type=int, default=800)
        parser.add_argument("--actor", default="user:slobodan")

    def handle(self, *args, op, provider, model, purpose, priority, in_usd, out_usd,
               max_output, actor, **opts):
        if op == "list":
            for r in LLMRoute.objects.order_by("purpose", "priority"):
                self.stdout.write(
                    f"{r.purpose:14} {r.provider}/{r.model_key:28} prio {r.priority:<5} "
                    f"{'UKLJUČENA' if r.is_enabled else 'isključena':10} "
                    f"ulaz {r.input_price_micro_eur_per_1k} / izlaz "
                    f"{r.output_price_micro_eur_per_1k} µEUR/1k")
            return
        if not (provider and model):
            raise CommandError("--provider i --model su obavezni.")
        with bind(actor_id=actor):
            if op == "add":
                r, created = LLMRoute.objects.update_or_create(
                    purpose=purpose, provider=provider, model_key=model,
                    defaults={"name": f"{provider} {model}", "priority": priority,
                              "is_enabled": False, "max_output_tokens": max_output,
                              "data_training_allowed": provider in NO_TRAINING,
                              "is_openai_compatible": provider != "anthropic",
                              "input_price_micro_eur_per_1k": _micro_eur_per_1k(in_usd),
                              "output_price_micro_eur_per_1k": _micro_eur_per_1k(out_usd),
                              "quota_json": {"thinking": "disabled"}})
                audit.record("llm.route.added", details={"route": f"{provider}/{model}",
                                                         "purpose": purpose})
                self.stdout.write(f"{'Dodata' if created else 'Ažurirana'} (isključena): "
                                  f"{provider}/{model} za {purpose}.")
                return
            r = LLMRoute.objects.filter(purpose=purpose, provider=provider,
                                        model_key=model).first()
            if r is None:
                raise CommandError("Ruta ne postoji.")
            r.is_enabled = op == "enable"
            r.save(update_fields=["is_enabled", "updated_at"])
            audit.record(f"llm.route.{op}d", severity=E.AuditSeverity.WARNING,
                         details={"route": f"{provider}/{model}", "purpose": purpose})
            state = "UKLJUČENA" if r.is_enabled else "isključena"
            self.stdout.write(f"{provider}/{model}: {state}.")
