"""Testovi F1 šeme — da modeli odgovaraju Canon-u v1.1.

Podeljeni su na dve grupe. Strukturni testovi čitaju `_meta` i rade bez
baze: oni hvataju upravo one greške koje su i nastale pri pisanju F1
(polje sa ukinutim imenom, nedostajuće ograničenje, model u pogrešnom
app-u). Testovi sa `requires_db` proveravaju da ograničenja zaista rade
u PostgreSQL-u, jer CHECK koji postoji u modelu a ne u bazi ne štiti ništa.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.apps import apps
from django.db import IntegrityError, transaction
from django.db.utils import DataError

from common import enums as E
from tests.conftest import requires_db

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _model(label: str):
    return apps.get_model(label)


def _constraint_names(model) -> set[str]:
    return {c.name for c in model._meta.constraints}


def _field_names(model) -> set[str]:
    return {f.name for f in model._meta.get_fields()}


# ------------------------------------------------------------- vlasništvo §1


class TestAppOwnership:
    """Canon §1 — jedan app, jedan vlasnik tabela."""

    OWNERSHIP = {
        "personas": {
            "Persona", "PersonaAlias", "PersonaTag", "PersonaTagLink",
            "Biography", "LifeEvent", "IdentityFact", "TraitProfile",
            "VoiceProfile",
        },
        "visuals": {
            "VisualProfile", "MediaAsset", "AssetCollection", "AssetCollectionItem",
        },
        "behaviour": {
            "BehaviourState", "RoutineTemplate", "RoutineWindow", "WorldEvent",
            "StateDelta",
        },
        "memory": {
            "MemoryItem", "MemoryEmbedding", "MemoryLink", "MemorySource",
            "MemoryContradiction", "MemoryContextPack", "KnowledgeSource",
            "KnowledgeFact",
        },
        "social_graph": {"Actor", "Relationship", "RelationshipEvent"},
        "content": {"ContentIdea", "ContentItem", "ContentAsset", "Publication"},
        "channels": {
            "ChannelAccount", "ChannelCapability", "IntegrationEndpoint",
            "MailMessage",
        },
        "orchestration": {
            "AgentRun", "AgentPlan", "PlanStep", "Action", "ActionAttempt",
        },
        "policy": {
            "PolicyRule", "PolicyDecision", "ApprovalRequest", "CapabilityGrant",
            "TrustState", "KillSwitch", "PolicyIncident",
        },
        "runtime": {
            "BrowserProfile", "RuntimeSession", "WorkerJob", "ReconcileTask",
        },
        "observability": {
            "AuditEvent", "MetricPoint", "CostLedger",
            "EventOutbox", "EventDelivery", "IdempotencyRecord",
        },
        "llm_gateway": {"LLMRoute", "PromptRecord", "LLMUsage"},
    }

    @pytest.mark.parametrize("app_label", sorted(OWNERSHIP))
    def test_app_ima_tacno_svoje_modele(self, app_label):
        found = {m.__name__ for m in apps.get_app_config(app_label).get_models()}
        assert found == self.OWNERSHIP[app_label]

    def test_svih_dvanaest_app_ova_postoji(self):
        assert len(self.OWNERSHIP) == 12

    def test_world_event_je_u_behaviour_a_ne_u_orchestration(self):
        """Canon §1 — događaj menja stanje; plan je posledica stanja."""
        assert _model("behaviour.WorldEvent") is not None
        with pytest.raises(LookupError):
            _model("orchestration.WorldEvent")

    def test_mail_message_je_u_channels_a_ne_u_runtime(self):
        assert _model("channels.MailMessage") is not None
        with pytest.raises(LookupError):
            _model("runtime.MailMessage")


# ------------------------------------------------------------ imena polja §4


class TestCanonicalFieldNames:
    def test_behaviour_state_ima_svih_osamnaest_polja(self):
        """Canon §4.2."""
        expected = {
            "energy", "valence", "arousal", "cognitive_load", "social_appetite",
            "curiosity_now", "focus", "novelty_need", "stress",
            "content_pressure", "inbox_pressure", "topic_saturation",
            "risk_alert", "free_minutes", "attention_remaining", "next_wake_at",
            "wake_priority", "state_version",
        }
        assert expected <= _field_names(_model("behaviour.BehaviourState"))

    def test_behaviour_state_nema_ukinuta_imena(self):
        """Canon §4.2 — `mood`, `fatigue` i stara imena opterećenja ne postoje."""
        fields = _field_names(_model("behaviour.BehaviourState"))
        for retired in ("mood", "mood_positive", "mood_valence", "fatigue"):  # canon-lint: allow
            assert retired not in fields

    def test_trait_profile_ima_kanonskih_dvanaest(self):
        """Canon §5."""
        from apps.personas.models import CANONICAL_TRAITS

        assert len(CANONICAL_TRAITS) == 12
        fields = _field_names(_model("personas.TraitProfile"))
        assert set(CANONICAL_TRAITS) <= fields
        # `verbosity` je stil, ne osobina — seli se u VoiceProfile.
        assert "verbosity" not in fields
        assert "verbosity" in _field_names(_model("personas.VoiceProfile"))

    def test_curiosity_je_osobina_a_curiosity_now_stanje(self):
        """Canon §4.2 — nijedno ime nije i osobina i stanje."""
        traits = _field_names(_model("personas.TraitProfile"))
        state = _field_names(_model("behaviour.BehaviourState"))
        assert "curiosity" in traits and "curiosity" not in state
        assert "curiosity_now" in state and "curiosity_now" not in traits

    def test_memorija_koristi_salience_a_ne_ukinuto_ime(self):
        """Canon §10.1."""
        fields = _field_names(_model("memory.MemoryItem"))
        assert "salience" in fields
        assert "importance" not in fields

    def test_akcija_nema_zonu_kao_kolonu(self):
        """Canon §3.7 — zona je izvedena oznaka, nikada kolona."""
        fields = _field_names(_model("orchestration.Action"))
        assert "risk_score" in fields and "risk_class" in fields
        assert "risk_level" not in fields
        assert "zone" not in fields

    def test_ishod_zivi_na_pokusaju_a_ne_na_akciji(self):
        """Canon §3.9 — inače bi UNKNOWN_EFFECT bio prepisan."""
        assert "outcome" in _field_names(_model("orchestration.ActionAttempt"))
        assert "outcome" not in _field_names(_model("orchestration.Action"))

    def test_cost_ledger_je_u_eur_centima(self):
        """Canon §13.1 — jedna valuta, celi centi."""
        fields = _field_names(_model("observability.CostLedger"))
        assert {"amount_eur_cents", "source_currency", "source_amount_minor",
                "fx_rate", "fx_date", "cost_bucket"} <= fields
        assert "cost_amount" not in fields

    def test_browser_profile_ima_polja_iz_canon_12_7(self):
        fields = _field_names(_model("runtime.BrowserProfile"))
        assert {"allowed_domains", "blocked_domains", "max_session_seconds",
                "kill_switch_enabled", "auth_state", "snapshot_version"} <= fields

    def test_email_nalog_ima_polja_iz_canon_12_8(self):
        fields = _field_names(_model("channels.ChannelAccount"))
        assert {"persona_address", "sending_domain", "dkim_selector",
                "warmup_started_at", "daily_cap"} <= fields


# ------------------------------------------------------- ograničenja u bazi


class TestConstraintsDeclared:
    def test_akcija_trazi_policy_odluku(self):
        """Canon §6.2, §16.5 — hard KPI sproveden u bazi, ne u servisu."""
        assert "action_requires_policy_decision" in _constraint_names(
            _model("orchestration.Action")
        )

    def test_idempotency_key_je_jedinstven(self):
        """Canon §6.3, §16.5 — duplirani spoljašnji efekat je NO-GO."""
        field = _model("orchestration.Action")._meta.get_field("idempotency_key")
        assert field.unique is True
        assert field.null is False

    def test_rezervisani_trust_nivoi_blokirani_na_tri_mesta(self):
        """Canon §3.11 (A-08)."""
        assert "persona_trust_level_assignable" in _constraint_names(
            _model("personas.Persona")
        )
        assert "capability_grant_trust_assignable" in _constraint_names(
            _model("policy.CapabilityGrant")
        )
        assert "trust_state_level_assignable" in _constraint_names(
            _model("policy.TrustState")
        )

    def test_kanali_van_opsega_blokirani(self):
        """Canon §16.2 (A-10) — TikTok i YouTube nemaju adapter, pa ni nalog."""
        assert "channel_account_no_out_of_scope" in _constraint_names(
            _model("channels.ChannelAccount")
        )

    def test_samo_playwright(self):
        """Canon §12.1 — stealth fork je u koliziji sa §9.4 tačkom 4."""
        assert "browser_profile_engine_playwright_only" in _constraint_names(
            _model("runtime.BrowserProfile")
        )

    def test_jedna_write_sesija_po_personi(self):
        """Canon §12.2."""
        assert "runtime_session_one_write_per_persona" in _constraint_names(
            _model("runtime.RuntimeSession")
        )

    def test_embedding_dimenzija_dolazi_iz_podesavanja(self):
        """Canon §10.5 — nikada hardkodovano."""
        from django.conf import settings

        field = _model("memory.MemoryEmbedding")._meta.get_field("embedding")
        assert field.dimensions == settings.EMBEDDING_DIM


# ------------------------------------------------------------- ponašanje DB


@requires_db
@pytest.mark.django_db
class TestConstraintsEnforced:
    """Ograničenje koje postoji u modelu a ne radi u bazi ne štiti ništa."""

    @staticmethod
    def _persona(**kwargs):
        from apps.personas.models import Persona

        base = dict(
            public_id="P-09001",
            slug="test-persona",
            display_name="Test (AI)",
            persona_type=E.PersonaType.AI_CREATOR,
            status=E.PersonaStatus.DRAFT,
            disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE,
            primary_locale="sr-Latn",
            timezone="Europe/Belgrade",
        )
        return Persona.objects.create(**(base | kwargs))

    def test_l3_se_ne_moze_dodeliti(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                self._persona(trust_level=E.TrustLevel.L3)

    def test_arhivirana_persona_mora_imati_datum(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                self._persona(status=E.PersonaStatus.ARCHIVED, archived_at=None)

    def test_tiktok_nalog_se_ne_moze_napraviti(self):
        from apps.channels.models import ChannelAccount

        persona = self._persona()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ChannelAccount.objects.create(
                    persona=persona,
                    channel_type=E.ChannelType.TIKTOK,
                    identity_vehicle=E.IdentityVehicle.PROFILE,
                    handle="test",
                )

    def test_akcija_bez_odluke_ne_moze_u_queued(self):
        """Canon §6.2 — `actions_without_policy_decision = 0`."""
        from apps.orchestration.models import Action

        persona = self._persona()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Action.objects.create(
                    public_id="ACT-01K5XQTESTTESTTESTTESTTEST",
                    persona=persona,
                    action_type="channel.post.create",
                    status=E.ActionStatus.QUEUED,
                    intent="test",
                    idempotency_key="test-key-1",
                )

    def test_akcija_bez_odluke_sme_da_bude_predlozena(self):
        from apps.orchestration.models import Action

        persona = self._persona()
        action = Action.objects.create(
            public_id="ACT-01K5XQTESTTESTTESTTESTTES2",
            persona=persona,
            action_type="channel.post.create",
            status=E.ActionStatus.PROPOSED,
            intent="test",
            idempotency_key="test-key-2",
        )
        assert action.policy_decision_id is None

    def test_valence_sme_negativan_a_energija_ne(self):
        """Canon §4.2 — `valence` je jedino polje sa negativnim opsegom."""
        from apps.behaviour.models import BehaviourState

        persona = self._persona()
        base = {k: Decimal("0.500") for k in (
            "energy", "arousal", "cognitive_load", "social_appetite",
            "curiosity_now", "focus", "novelty_need", "stress",
            "content_pressure", "inbox_pressure", "topic_saturation",
            "risk_alert",
        )}
        state = BehaviourState.objects.create(
            persona=persona,
            valence=Decimal("-0.750"),
            free_minutes=120,
            attention_remaining=Decimal("6.00"),
            **base,
        )
        assert state.valence == Decimal("-0.750")

        state.energy = Decimal("-0.100")
        with pytest.raises((IntegrityError, DataError)):
            with transaction.atomic():
                state.save()

    def test_memorija_bez_naslednika_ne_moze_biti_superseded(self):
        from apps.memory.models import MemoryItem

        persona = self._persona()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                MemoryItem.objects.create(
                    persona=persona,
                    memory_type=E.MemoryType.EPISODIC,
                    status=E.MemoryStatus.SUPERSEDED,
                    provenance=E.Provenance.OBSERVED,
                    content="x",
                    salience=Decimal("0.500"),
                    confidence=Decimal("0.500"),
                )


@requires_db
@pytest.mark.django_db
class TestSeed:
    def test_seed_je_idempotentan_i_u_simulaciji(self):
        from django.core.management import call_command

        from apps.personas.models import Persona, TraitProfile
        from apps.policy.models import PolicyRule

        call_command("seed_agent_001", verbosity=0)
        call_command("seed_agent_001", verbosity=0)

        assert Persona.objects.filter(public_id="P-00001").count() == 1
        persona = Persona.objects.get(public_id="P-00001")

        # Canon §16.2 — Pilot A počinje u SIMULATION.
        assert persona.runtime_environment == E.RuntimeEnvironment.SIMULATION
        assert persona.trust_level == E.TrustLevel.L0
        assert persona.disclosure_required is True
        # Canon §17 — nijedan državni identifikator ni legal_identity.
        assert persona.birth_date_model is None

        traits = TraitProfile.objects.get(persona=persona)
        assert traits.openness == Decimal("0.860")
        assert traits.evidence_preference == Decimal("0.840")

        # Canon §9.4 — tvrde zabrane su DENY i ne mogu se isključiti.
        denies = PolicyRule.objects.filter(
            effect=E.PolicyEffect.DENY, is_hard_prohibition=True
        )
        assert denies.count() >= 4
        assert all(r.is_enabled for r in denies)

    def test_seed_ne_pravi_stvarni_kanal(self):
        from django.core.management import call_command

        from apps.channels.models import ChannelAccount

        call_command("seed_agent_001", verbosity=0)
        types = set(
            ChannelAccount.objects.values_list("channel_type", flat=True)
        )
        assert types == {E.ChannelType.SANDBOX.value}
