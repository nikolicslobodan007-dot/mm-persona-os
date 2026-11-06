"""manage.py seed_asr_lokalni — lokalni Whisper kao TRANSCRIBE ruta; Groq isključen.

Groq je ograničen (ToS ban), pa ASR prelazi na lokalni Whisper (faster-whisper):
bez naloga, bez troška, nezavisno od spoljnog provajdera. Idempotentno.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.llm_gateway.models import LLMRoute
from common import enums as E


class Command(BaseCommand):
    help = "Zaseje lokalni Whisper TRANSCRIBE rutu i isključi Groq (idempotentno)."

    def handle(self, *args, **o):
        ruta, napravljeno = LLMRoute.objects.update_or_create(
            purpose=E.LLMPurpose.TRANSCRIBE.value,
            provider="local_whisper",
            model_key="base",
            defaults={
                "name": "Lokalni Whisper (faster-whisper base)",
                "priority": 0,
                "is_enabled": True,
                "is_openai_compatible": False,
                "base_url": "",
                "timeout_seconds": 600,
                "data_training_allowed": True,
                "input_price_micro_eur_per_1k": 0,
                "output_price_micro_eur_per_1k": 0,
                "quota_json": {},
                "notes": "Lokalni ASR (izolovan venv). tin=sekunde audija; bez troška.",
            },
        )
        iskljuceno = LLMRoute.objects.filter(
            purpose=E.LLMPurpose.TRANSCRIBE.value, provider="groq", is_enabled=True,
        ).update(is_enabled=False)
        self.stdout.write(self.style.SUCCESS(
            ("Napravljeno: " if napravljeno else "Ažurirano: ") + str(ruta)
            + f" · Groq ruta isključena: {iskljuceno}"))
