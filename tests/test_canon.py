"""Testovi kanonskih invarijanti — MM Persona OS Canon v1.1.

Ne testiraju Django. Testiraju da `common/` odgovara Canon-u: ako neko
promeni enum ili ID format bez ADR-a, ovi testovi padaju.
"""

from __future__ import annotations

import json
import pathlib
import re
from datetime import UTC, date, datetime

import pytest
import yaml

from common import enums as E
from common import ids as I
from common.events import (
    EVENT_OWNERS,
    EVENT_TYPES,
    RETIRED_EVENT_TYPES,
    EventEnvelope,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


# ---------------------------------------------------------------- ID-jevi §2


class TestPublicIds:
    def test_persona_ima_pet_cifara(self):
        assert I.persona_public_id(1) == "P-00001"
        assert I.persona_public_id(37) == "P-00037"
        assert I.persona_public_id(99999) == "P-99999"

    @pytest.mark.parametrize(
        "bad", ["P-001", "P001", "P0001", "P-1", "p-00001"]  # canon-lint: allow
    )
    def test_kratki_oblici_su_odbijeni(self, bad):
        """Canon §2.2 — Faza 13 koristi trocifreni oblik, to je errata §19."""
        with pytest.raises(ValueError):
            I.validate_public_id(I.EntityKind.PERSONA, bad)

    @pytest.mark.parametrize("bad", [0, -1, 100000, 1.0, True, "5"])
    def test_van_opsega_i_pogresan_tip(self, bad):
        with pytest.raises((ValueError, TypeError)):
            I.persona_public_id(bad)

    def test_round_trip(self):
        for n in (1, 42, 99999):
            assert I.parse_persona_number(I.persona_public_id(n)) == n

    def test_svaki_entitet_ima_spec(self):
        kinds = {
            v for k, v in vars(I.EntityKind).items() if not k.startswith("_")
        }
        assert kinds == set(I.SPECS), "Canon §2.2 — devet entiteta, devet oblika"
        assert len(I.SPECS) == 9

    @pytest.mark.parametrize("kind", sorted(I._ULID_KINDS))
    def test_ulid_oblik(self, kind):
        pid = I.ulid_public_id(kind)
        assert I.validate_public_id(kind, pid) == pid
        assert I.kind_of(pid) == kind

    def test_ulid_je_sortabilan_po_vremenu(self):
        """Ceo razlog izbora ULID-a nad UUID-om (Canon §2.2)."""
        t1 = datetime(2026, 9, 16, 8, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 9, 16, 9, 0, 0, tzinfo=UTC)
        assert I.new_ulid(t1) < I.new_ulid(t2)

    def test_ulid_nema_dvosmislene_znakove(self):
        """Crockford base32 izostavlja I, L, O, U."""
        for ch in "ILOU":
            assert ch not in I._CROCKFORD
        assert not set(I.new_ulid()) & set("ILOU")

    def test_media_asset_i_incident(self):
        assert I.media_asset_public_id("P-00001", 47) == "IMG-P00001-0047"
        assert I.incident_public_id(date(2026, 9, 15), 1) == "INC-20260915-001"
        with pytest.raises(ValueError):
            I.media_asset_public_id("P-001", 47)  # canon-lint: allow

    def test_kind_of_odbija_nepoznato(self):
        with pytest.raises(ValueError):
            I.kind_of("XYZ-123")


# ---------------------------------------------------------------- enum-i §3


class TestEnums:
    def test_persona_status_bez_ukinutih(self):
        v = set(E.PersonaStatus.values())
        assert v == {"DRAFT", "READY", "ACTIVE", "PAUSED", "DEGRADED",
                     "SUSPENDED", "ARCHIVED"}
        assert "pilot_active" not in v and "retired" not in v  # canon-lint: allow

    def test_policy_effect_ima_throttle_a_ne_rate_limit(self):
        assert "THROTTLE" in E.PolicyEffect.values()
        assert "RATE_LIMIT" not in E.PolicyEffect.values()  # canon-lint: allow

    def test_zona_se_izvodi_iz_odluke_ne_iz_skora(self):
        """Canon §3.7 — najozbiljnija kolizija u dokumentaciji."""
        assert set(E.EFFECT_TO_ZONE) == set(E.PolicyEffect)
        assert E.EFFECT_TO_ZONE[E.PolicyEffect.ALLOW] is E.Zone.GREEN
        assert E.EFFECT_TO_ZONE[E.PolicyEffect.THROTTLE] is E.Zone.GREEN
        assert E.EFFECT_TO_ZONE[E.PolicyEffect.REQUIRE_APPROVAL] is E.Zone.YELLOW
        assert E.EFFECT_TO_ZONE[E.PolicyEffect.DENY] is E.Zone.RED

    def test_risk_bands_pokrivaju_ceo_opseg_bez_preklapanja(self):
        seen = set()
        for low, high, _ in E.RISK_BANDS:
            rng = set(range(low, high + 1))
            assert not (seen & rng), "opsezi se preklapaju"
            seen |= rng
        assert seen == set(range(101))

    @pytest.mark.parametrize("score,expected", [
        (0, "LOW"), (24, "LOW"), (25, "MEDIUM"), (49, "MEDIUM"),
        (50, "HIGH"), (62, "HIGH"), (74, "HIGH"), (75, "CRITICAL"), (100, "CRITICAL"),
    ])
    def test_risk_class_granice(self, score, expected):
        assert E.risk_class_for(score).value == expected

    @pytest.mark.parametrize("bad", [-1, 101, 0.5, "50", True])
    def test_risk_score_je_ceo_broj_0_100(self, bad):
        """Canon §3.6 — nikada decimala 0–1."""
        with pytest.raises((ValueError, TypeError)):
            E.risk_class_for(bad)

    def test_outcome_i_status_su_razdvojeni(self):
        """Canon §3.9 — četiri dokumenta su ovo mešala u jedan enum."""
        assert set(E.ExecutionOutcome.values()) & set(E.ActionStatus.values()) == {
            "SUCCEEDED"
        }, "samo SUCCEEDED se poklapa po imenu, i to namerno"

    def test_svaki_outcome_ima_prelaz(self):
        assert set(E.OUTCOME_TO_STATUS) == set(E.ExecutionOutcome)

    def test_unknown_effect_ne_vodi_u_retry(self):
        """Canon §3.9, §12.3 — jedino stanje koje može proizvesti duplikat."""
        assert E.OUTCOME_TO_STATUS[E.ExecutionOutcome.UNKNOWN_EFFECT] is None

    def test_capability_unavailable_nije_greska(self):
        """Canon §12.1 — 'unsupported' je validan ishod."""
        assert (E.OUTCOME_TO_STATUS[E.ExecutionOutcome.CAPABILITY_UNAVAILABLE]
                is E.ActionStatus.CANCELLED)

    def test_novi_ishodi_iz_v1_1(self):
        assert (E.OUTCOME_TO_STATUS[E.ExecutionOutcome.PLATFORM_POLICY_REQUIRES_HUMAN]
                is E.ActionStatus.CANCELLED)
        assert (E.OUTCOME_TO_STATUS[E.ExecutionOutcome.DISCLOSURE_MISSING]
                is E.ActionStatus.BLOCKED)

    def test_l3_l4_su_rezervisani(self):
        """Canon §3.11 (A-08) — nemaju kanal na kom se izvršavaju."""
        assert E.TrustLevel.L3 not in E.ASSIGNABLE_TRUST_LEVELS
        assert E.TrustLevel.L4 not in E.ASSIGNABLE_TRUST_LEVELS
        assert E.ASSIGNABLE_TRUST_LEVELS == {
            E.TrustLevel.L0, E.TrustLevel.L1, E.TrustLevel.L2
        }

    def test_memory_tipovi_su_mala_slova(self):
        assert set(E.MemoryType.values()) == {
            "working", "episodic", "semantic", "procedural", "social", "content"
        }
        assert "RELATIONSHIP" not in E.MemoryType.values()

    def test_svaki_memory_tip_ima_poluzivot(self):
        assert set(E.MEMORY_HALF_LIFE_DAYS) == set(E.MemoryType)
        assert E.MEMORY_HALF_LIFE_DAYS[E.MemoryType.PROCEDURAL] is None

    def test_deset_queue_ova_plus_dlq(self):
        """Canon §11.3 — deset, i ni jedan više."""
        assert len(E.QueueName) == 11
        assert E.QueueName.DEAD_LETTER.value == "dead_letter"

    def test_svaki_wake_priority_ima_vrednost(self):
        assert set(E.WAKE_PRIORITY_VALUE) == set(E.WakePriority)
        assert E.WAKE_PRIORITY_VALUE[E.WakePriority.OPERATOR_TASK] == 100

    def test_x_api_credits_je_zaseban_bucket(self):
        """Canon §13.2 (A-07) — X naplaćuje po objavi."""
        assert "x_api_credits" in E.CostBucket.values()

    def test_disclosure_ok_skup(self):
        assert E.DISCLOSURE_OK == {
            E.DisclosureLabelStatus.SET, E.DisclosureLabelStatus.NOT_REQUIRED
        }
        assert E.DisclosureLabelStatus.REQUIRED_NOT_SET not in E.DISCLOSURE_OK

    def test_tiktok_i_youtube_van_opsega(self):
        """Canon §16.2 (A-10)."""
        assert E.OUT_OF_SCOPE_CHANNELS == {E.ChannelType.TIKTOK, E.ChannelType.YOUTUBE}

    def test_sest_rbac_uloga(self):
        assert len(E.Role) == 6
        assert "reviewer" not in E.Role.values(), "reviewer je dozvola, ne uloga"

    def test_svaka_klasa_odobrenja_ima_ttl_i_efekat(self):
        assert set(E.APPROVAL_TTL_MINUTES) == set(E.ApprovalClass)
        assert set(E.APPROVAL_EXPIRY_EFFECT) == set(E.ApprovalClass)
        assert E.APPROVAL_TTL_MINUTES[E.ApprovalClass.A4] == 30

    def test_error_kodovi_imaju_http_status(self):
        assert set(E.ERROR_HTTP_STATUS) == set(E.ErrorCode)
        assert E.ERROR_HTTP_STATUS[E.ErrorCode.POLICY_BLOCKED] == 422
        assert E.ERROR_HTTP_STATUS[E.ErrorCode.RATE_LIMITED] == 429


# ---------------------------------------------------------------- eventi §7


class TestEvents:
    def test_dvadeset_tri_eventa(self):
        assert len(EVENT_TYPES) == 23

    def test_imena_prate_konvenciju(self):
        """Canon §0.3 — lowercase.dot.separated, glagol u prošlom vremenu."""
        rx = re.compile(r"^[a-z_]+(\.[a-z_]+){1,3}$")
        for et in EVENT_TYPES:
            assert rx.match(et), et

    def test_svaki_event_ima_vlasnika_iz_canon_1(self):
        apps = {"personas", "visuals", "behaviour", "memory", "social_graph",
                "content", "channels", "orchestration", "policy", "runtime",
                "observability", "llm_gateway"}
        assert set(EVENT_OWNERS.values()) <= apps

    def test_svaki_event_ima_semu(self):
        for et in EVENT_TYPES:
            p = ROOT / "schemas" / "events" / et / "1.json"
            assert p.exists(), f"nedostaje šema za {et}"
            schema = json.loads(p.read_text(encoding="utf-8"))
            assert schema["properties"]["event_type"]["const"] == et

    def test_nema_seme_van_kataloga(self):
        d = ROOT / "schemas" / "events"
        assert {p.name for p in d.iterdir() if p.is_dir()} == set(EVENT_TYPES)

    def test_ukinuti_eventi_su_odbijeni(self):
        for retired in RETIRED_EVENT_TYPES:
            with pytest.raises(ValueError, match="ukinuto"):
                EventEnvelope(event_type=retired, persona_id="P-00001",
                              trace_id=TRACE, run_id="RUN-" + I.new_ulid())

    def test_nepoznat_event_je_odbijen(self):
        with pytest.raises(ValueError, match="katalogu"):
            EventEnvelope(event_type="nesto.izmisljeno", persona_id="P-00001",
                          trace_id=TRACE, run_id="RUN-" + I.new_ulid())

    def test_trace_id_je_uvek_obavezan(self):
        with pytest.raises(ValueError, match="trace_id"):
            EventEnvelope(event_type="action.proposed", persona_id="P-00001",
                          trace_id="", run_id="RUN-" + I.new_ulid())

    def test_run_id_obavezan_gde_treba(self):
        """Canon §7.1 — obavezan unutar buđenja persone, null van njega."""
        # ADR-0007: action.proposed sme i van buđenja (operatorski predlog);
        # plan.created nastaje samo u buđenju i run_id mu je uvek obavezan.
        with pytest.raises(ValueError, match="run_id"):
            EventEnvelope(event_type="plan.created", persona_id="P-00001",
                          trace_id=TRACE)
        ev = EventEnvelope(event_type="killswitch.activated", persona_id=None,
                           trace_id=TRACE)
        assert ev.run_id is None

    def test_envelope_ima_kanonska_polja(self):
        ev = EventEnvelope(event_type="action.succeeded", persona_id="P-00001",
                           trace_id=TRACE, run_id="RUN-" + I.new_ulid())
        assert set(ev.to_dict()) == {
            "event_id", "event_type", "event_version", "occurred_at",
            "persona_id", "trace_id", "run_id", "causation_id", "payload",
        }
        assert ev.occurred_at.endswith("Z"), "Canon §7.1 — UTC sa Z sufiksom"
        assert ev.event_id.startswith("EVT-")


# ---------------------------------------------------- konfiguracije §3.14, §6.4


class TestConfigs:
    @staticmethod
    def _load(rel):
        return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))

    def test_identity_vehicles_pokriva_sve_kanale(self):
        data = self._load("channels/identity_vehicles.yaml")
        assert set(data["channels"]) == set(E.ChannelType.values())

    def test_linkedin_i_facebook_samo_page(self):
        """Aneks A §3.1 — lični profil je zabranjen, i uz označavanje."""
        data = self._load("channels/identity_vehicles.yaml")
        for ch in ("LINKEDIN", "FACEBOOK"):
            assert data["channels"][ch]["vehicles"] == ["PAGE"]
            assert "PROFILE" in data["channels"][ch]["forbidden_vehicles"]

    def test_linkedin_trazi_imenovanog_admina(self):
        data = self._load("channels/identity_vehicles.yaml")
        assert data["channels"]["LINKEDIN"]["requires_named_human_admin"] is True

    def test_kanali_van_opsega_nemaju_vozilo(self):
        data = self._load("channels/identity_vehicles.yaml")
        for ch in E.OUT_OF_SCOPE_CHANNELS:
            cfg = data["channels"][ch.value]
            assert cfg["in_scope"] is False
            assert cfg["vehicles"] == []

    def test_instagram_trazi_oznaku(self):
        data = self._load("channels/identity_vehicles.yaml")
        ig = data["channels"]["INSTAGRAM"]
        assert ig["disclosure_required"] is True
        assert ig["disclosure_label"] == "AI generated profile"

    def test_capabilities_ne_traze_rezervisan_trust(self):
        data = self._load("policy/capabilities.yaml")
        assignable = {t.value for t in E.ASSIGNABLE_TRUST_LEVELS}
        for name, cfg in data["capabilities"].items():
            assert cfg["min_trust_level"] in assignable, name

    def test_ukinuti_capability_ji_nisu_aktivni(self):
        data = self._load("policy/capabilities.yaml")
        assert "social.first_dm" not in data["capabilities"]  # canon-lint: allow
        assert "email.first_outbound" not in data["capabilities"]
        assert set(data["retired_capabilities"]) == {
            "social.first_dm", "email.first_outbound"  # canon-lint: allow
        }

    def test_web_read_public_ima_sva_cetiri_parametra(self):
        """Canon §6.4 — akcija bez sva četiri ne prolazi Capability korak."""
        data = self._load("policy/capabilities.yaml")
        rc = data["capabilities"]["web.read_public"]["required_constraints"]
        assert set(rc) == {"robots_respected", "user_agent_declared",
                           "rate_per_host_qps", "conditional_get"}
        assert rc["robots_respected"] is True
        assert rc["conditional_get"] is True

    def test_action_types_koriste_postojece_capability_je(self):
        data = self._load("policy/capabilities.yaml")
        caps = set(data["capabilities"])
        for at, needed in data["action_types"].items():
            assert set(needed) <= caps, at

    def test_hard_prohibitions_pokrivaju_canon_9_4(self):
        data = self._load("policy/capabilities.yaml")
        ids_ = {p["id"] for p in data["hard_prohibitions"]}
        assert ids_ == {
            "IDENTITY_IMPERSONATION", "DISCLOSURE_CONCEALMENT",
            "GOVERNMENT_IDENTIFIERS", "PLATFORM_EVASION", "BULK_UNSOLICITED",
            "SENSITIVE_DATA_SOLICITATION", "REAL_PERSON_LIKENESS",
        }, "Canon §9.4 — sedam tvrdih zabrana"

    def test_ukupni_plafon_se_primenjuje_prvi(self):
        """Canon §9.3 — zbir pojedinačnih je namerno veći od plafona."""
        data = self._load("policy/capabilities.yaml")
        rl = data["rate_limits_per_persona_day"]
        total = rl.pop("total_actions")
        assert total == 40
        assert sum(rl.values()) > total

    def test_risk_bands_u_yaml_u_prate_canon(self):
        data = self._load("policy/risk_weights.yaml")
        for low, high, klass in E.RISK_BANDS:
            assert data["risk_bands"][klass.value] == [low, high]

    def test_rezervisani_trust_nivoi_nemaju_kredit(self):
        data = self._load("policy/risk_weights.yaml")
        assert data["trust_credit"]["L3"] == 0
        assert data["trust_credit"]["L4"] == 0

    def test_nedostajuca_oznaka_nosi_visok_rizik(self):
        """Canon §3.16 — kanal bez oznake praktično ne prolazi."""
        data = self._load("policy/risk_weights.yaml")
        assert data["identity_risk"]["disclosure_missing"] >= 50
