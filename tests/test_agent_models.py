"""ADR-0026 — ključevi agenata i rute po agentu.

  - ključ ide u fajl sa pravima 0600, u bazi ostaje samo referenca;
  - vrednost se posle upisa ne može pročitati ni iz baze ni iz konzole;
  - agentova ruta ide ispred firmine, pa lokalni šablon ostaje poslednji;
  - ruta bez ključa se preskače, ma koliko bila jeftina;
  - uklanjanje ključa briše i fajl.
"""

from __future__ import annotations

import os
import stat

import pytest

from api.context import bind
from apps.llm_gateway import gateway
from apps.llm_gateway import secrets as agent_secrets
from apps.llm_gateway.models import AgentCredential, AgentRoute, LLMRoute
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
KLJUC = "sk-test-0123456789abcdef"


@pytest.fixture
def tajne(settings, tmp_path):
    settings.AGENT_SECRETS_DIR = str(tmp_path / "secrets")
    return tmp_path / "secrets"


@pytest.fixture
def jeftini():
    return LLMRoute.objects.create(
        purpose=E.LLMPurpose.CONTENT_DRAFT.value, name="Jeftin", provider="openrouter",
        model_key="mistral-small", priority=5, is_enabled=False,
        data_training_allowed=True, base_url="https://openrouter.ai/api/v1")


class TestKljuc:
    def test_value_goes_to_a_file_not_to_the_database(self, mila, tajne):
        with bind(actor_id="user:boss"):
            cred = agent_secrets.set_key(mila, "openrouter", KLJUC, actor="user:boss")
        assert cred.credential_ref.startswith("file:")
        assert KLJUC not in cred.credential_ref
        put = cred.credential_ref[5:]
        assert open(put, encoding="utf-8").read() == KLJUC
        # nijedno polje u bazi ne nosi vrednost
        red = AgentCredential.objects.values().get(pk=cred.pk)
        assert not any(KLJUC in str(v) for v in red.values())
        assert cred.fingerprint == KLJUC[-4:]

    def test_file_is_readable_only_by_the_owner(self, mila, tajne):
        with bind(actor_id="user:boss"):
            cred = agent_secrets.set_key(mila, "openrouter", KLJUC, actor="user:boss")
        rezim = stat.S_IMODE(os.stat(cred.credential_ref[5:]).st_mode)
        assert rezim == 0o600

    def test_database_refuses_a_row_that_is_not_a_reference(self, mila, tajne):
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            AgentCredential.objects.create(persona=mila, provider="x",
                                           credential_ref=KLJUC, set_by="user:boss")

    def test_bad_input_is_refused(self, mila, tajne):
        with pytest.raises(agent_secrets.SecretError):
            agent_secrets.set_key(mila, "../etc", KLJUC, actor="user:boss")
        with pytest.raises(agent_secrets.SecretError):
            agent_secrets.set_key(mila, "openrouter", "kratko", actor="user:boss")
        with pytest.raises(agent_secrets.SecretError):
            agent_secrets.set_key(mila, "openrouter", "sa razmakom u sredini",
                                  actor="user:boss")

    def test_removing_a_key_removes_the_file(self, mila, tajne):
        with bind(actor_id="user:boss"):
            cred = agent_secrets.set_key(mila, "openrouter", KLJUC, actor="user:boss")
            put = cred.credential_ref[5:]
            assert agent_secrets.drop_key(mila, "openrouter", actor="user:boss")
        assert not os.path.exists(put)
        assert not AgentCredential.objects.filter(persona=mila).exists()

    def test_gateway_finds_the_agents_key_first(self, mila, tajne, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "zajednicki-kljuc-123")
        with bind(actor_id="user:boss"):
            agent_secrets.set_key(mila, "anthropic", KLJUC, actor="user:boss")
        ref, izvor = gateway.credential_ref("anthropic", mila)
        assert izvor == "persona" and ref.startswith("file:")


class TestRuteAgenta:
    def test_agent_route_comes_before_the_company_one(self, mila, jeftini):
        skup = LLMRoute.objects.create(
            purpose=E.LLMPurpose.CONTENT_DRAFT.value, name="Skup", provider="anthropic",
            model_key="claude-sonnet-5", priority=1, is_enabled=True,
            data_training_allowed=True)
        AgentRoute.objects.create(persona=mila, purpose=E.LLMPurpose.CONTENT_DRAFT.value,
                                  route=jeftini, priority=0)
        redosled = gateway.routes(E.LLMPurpose.CONTENT_DRAFT, mila)
        assert redosled[0].pk == jeftini.pk          # agentova prva
        assert skup.pk in [r.pk for r in redosled]   # firmina i dalje tu
        assert redosled[-1].provider == gateway.LOCAL_PROVIDER

    def test_agent_can_use_a_model_the_company_has_not_enabled(self, mila, jeftini):
        """Ruta isključena za firmu je i dalje dostupna agentu kom je dodeljena."""
        assert not jeftini.is_enabled
        AgentRoute.objects.create(persona=mila, purpose=E.LLMPurpose.CONTENT_DRAFT.value,
                                  route=jeftini, priority=0)
        assert gateway.routes(E.LLMPurpose.CONTENT_DRAFT, mila)[0].pk == jeftini.pk

    def test_another_agent_is_not_affected(self, mila, jeftini):
        from apps.personas.models import Persona

        AgentRoute.objects.create(persona=mila, purpose=E.LLMPurpose.CONTENT_DRAFT.value,
                                  route=jeftini, priority=0)
        drugi = Persona.objects.create(
            public_id="P-00042", slug="p-00042", display_name="Drugi (AI)",
            persona_type=E.PersonaType.AI_CREATOR, status=E.PersonaStatus.READY,
            disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE, primary_locale="sr-Latn",
            timezone="Europe/Belgrade")
        vidi = [r.pk for r in gateway.routes(E.LLMPurpose.CONTENT_DRAFT, drugi)]
        assert jeftini.pk not in vidi          # tuđa ruta se ne nasleđuje

    def test_route_without_a_key_is_skipped(self, mila, jeftini, settings, tajne):
        settings.LLM_EXTERNAL_ENABLED = True
        assert gateway._external_allowed(jeftini, mila) == "NO_PERSONA_KEY"
        with bind(actor_id="user:boss"):
            agent_secrets.set_key(mila, "openrouter", KLJUC, actor="user:boss")
        assert gateway._external_allowed(jeftini, mila) is None

    def test_training_provider_is_refused_even_with_a_key(self, mila, settings, tajne):
        settings.LLM_EXTERNAL_ENABLED = True
        uci = LLMRoute.objects.create(
            purpose=E.LLMPurpose.CONTENT_DRAFT.value, name="Besplatan", provider="besplatni",
            model_key="free-1", is_enabled=True, data_training_allowed=False)
        with bind(actor_id="user:boss"):
            agent_secrets.set_key(mila, "besplatni", KLJUC, actor="user:boss")
        assert gateway._external_allowed(uci, mila) == "PROVIDER_MAY_TRAIN"
