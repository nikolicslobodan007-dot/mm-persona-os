"""manage.py seed_veritas_asr — zaseje Groq Whisper rutu za TRANSCRIBE. ADR-0125.

Idempotentno: ista (purpose, provider, model_key) se ažurira, ne duplira.
Ključ NIJE ovde — čita se iz GROQ_API_KEY (.env) preko LLM_CREDENTIALS.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.llm_gateway.models import LLMRoute
from common import enums as E


class Command(BaseCommand):
    help = "Zaseje Groq Whisper TRANSCRIBE rutu (idempotentno)."

    def handle(self, *args, **o):
        ruta, napravljeno = LLMRoute.objects.update_or_create(
            purpose=E.LLMPurpose.TRANSCRIBE.value,
            provider="groq",
            model_key="whisper-large-v3-turbo",
            defaults={
                "name": "Groq Whisper large-v3-turbo",
                "priority": 0,
                "is_enabled": True,
                "is_openai_compatible": True,
                "base_url": "https://api.groq.com/openai/v1",
                "timeout_seconds": 120,
                # Groq ne trenira na API podacima — sme da primi tuđi govor.
                "data_training_allowed": True,
                # Besplatni tier → 0. tin = sekunde audija; cena „po 1000 sekundi”.
                "input_price_micro_eur_per_1k": 0,
                "output_price_micro_eur_per_1k": 0,
                "quota_json": {"language": "sr"},
                "notes": "ADR-0125. tin=sekunde audija (ne tokeni); cena po 1000s ako se uključi.",
            },
        )
        self.stdout.write(self.style.SUCCESS(
            ("Napravljeno: " if napravljeno else "Ažurirano: ") + str(ruta)))
