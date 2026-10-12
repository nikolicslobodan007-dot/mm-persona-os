"""Transkripcija ćuti umesto da izmisli. ADR-0078.

Obrazac preuzet iz `TestGateway` u `tests/test_content.py`: `settings`
fixture za `LLM_EXTERNAL_ENABLED`, `LLMRoute.objects.create(...)` za rute,
`monkeypatch.setenv` za ključ u okruženju i `bind(actor_id="user:op")` oko
poziva gateway-a.

Za svrhu TRANSCRIBE lanac NEMA lokalni šablon kao poslednji član (ADR-0078
§4): šablon ne može da čuje, pa bi vratio izmišljen prepis. Zato se umesto
teksta uvek vraća `LLMError` sa kodom `LLM_EXTERNAL_DISABLED`, nikada tekst.
"""

from __future__ import annotations

import pytest

from api.context import bind
from apps.llm_gateway import gateway
from apps.llm_gateway.models import LLMRoute, PromptRecord
from apps.visuals.models import MediaAsset
from common import enums as E

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def audio_asset(mila):
    return MediaAsset.objects.create(
        persona=mila,
        kind=E.AssetKind.AUDIO,
        storage_key="audio/snimak-001.m4a",
        mime_type="audio/m4a",
        sha256="a" * 64,
        origin="user_owned",
    )


class TestTranscribe:
    def test_no_route_raises_llm_external_disabled_without_text(self, settings, audio_asset):
        """Nema nijedne rute za TRANSCRIBE — nema ni teksta, samo odbijanje."""
        settings.LLM_EXTERNAL_ENABLED = True
        with bind(actor_id="user:op"), pytest.raises(gateway.LLMError) as exc:
            gateway.transcribe(audio_asset)
        assert exc.value.code == "LLM_EXTERNAL_DISABLED"

    def test_only_local_route_still_disabled(self, settings, audio_asset):
        """Lokalni šablon nije u lancu ni kao poslednji — i dalje odbijanje."""
        settings.LLM_EXTERNAL_ENABLED = True
        LLMRoute.objects.create(
            purpose=E.LLMPurpose.TRANSCRIBE.value,
            name="Lokalni šablon",
            provider=gateway.LOCAL_PROVIDER,
            model_key="template-v1",
            priority=1,
            data_training_allowed=True,
        )
        with bind(actor_id="user:op"), pytest.raises(gateway.LLMError) as exc:
            gateway.transcribe(audio_asset)
        assert exc.value.code == "LLM_EXTERNAL_DISABLED"

    def test_external_route_but_disabled_writes_no_prompt_record(
        self, settings, audio_asset
    ):
        """Spoljna ruta postoji, ali LLM_EXTERNAL_ENABLED=False — ćutanje bez upisa."""
        settings.LLM_EXTERNAL_ENABLED = False
        LLMRoute.objects.create(
            purpose=E.LLMPurpose.TRANSCRIBE.value,
            name="Spoljni provajder",
            provider="anthropic",
            model_key="whisper-ish",
            priority=1,
            data_training_allowed=True,
        )
        before = PromptRecord.objects.count()
        with bind(actor_id="user:op"), pytest.raises(gateway.LLMError) as exc:
            gateway.transcribe(audio_asset)
        assert exc.value.code == "LLM_EXTERNAL_DISABLED"
        assert PromptRecord.objects.count() == before

    def test_unsupported_provider_still_ends_in_llm_external_disabled(
        self, settings, monkeypatch, audio_asset
    ):
        """Spoljna ruta uključena i ključ u okruženju — poziv pada na
        UNSUPPORTED_PROVIDER iz `_call_external_audio`, a `transcribe` to
        pretvara u LLM_EXTERNAL_DISABLED čija poruka nosi UNSUPPORTED_PROVIDER.
        Ni tada nema izmišljenog teksta."""
        settings.LLM_EXTERNAL_ENABLED = True
        route = LLMRoute.objects.create(
            purpose=E.LLMPurpose.TRANSCRIBE.value,
            name="Spoljni provajder",
            provider="anthropic",
            model_key="whisper-ish",
            priority=1,
            data_training_allowed=True,
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        settings.LLM_CREDENTIALS = {"anthropic": "env:ANTHROPIC_API_KEY"}
        with bind(actor_id="user:op"), pytest.raises(gateway.LLMError) as exc:
            gateway.transcribe(audio_asset)
        assert exc.value.code == "LLM_EXTERNAL_DISABLED"
        assert "UNSUPPORTED_PROVIDER" in exc.value.detail
        assert route.provider in exc.value.detail
