"""Seed referentne persone P-00001 — Mila Vuković. Canon v1.1 §17, šema §21.

Seed NE pravi nijedan spoljašnji nalog i ne izvršava nijednu mrežnu akciju.
Pravi samo interne redove i sandbox konfiguraciju.

Idempotentno: ponovno pokretanje ne duplira ništa (`update_or_create` po
prirodnim ključevima). Zato sme da se pokrene i na već zasejanoj bazi.

Pokretanje:
    python manage.py seed_agent_001
    python manage.py seed_agent_001 --reset   # briše i pravi iznova
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.behaviour.models import BehaviourState, RoutineTemplate, RoutineWindow
from apps.channels.models import ChannelAccount, ChannelCapability
from apps.memory.models import MemoryItem, MemorySource
from apps.personas.models import (
    Biography,
    IdentityFact,
    Persona,
    PersonaAlias,
    PersonaTag,
    PersonaTagLink,
    TraitProfile,
    VoiceProfile,
)
from apps.policy.models import PolicyRule
from apps.social_graph.models import Actor
from apps.visuals.models import VisualProfile
from common import enums as E
from common import ids as I

NOW = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

#: Canon §5 — vrednosti iz Agent 001 spec-a, ne izmišljene.
TRAITS: dict[str, str] = {
    "openness": "0.860",
    "conscientiousness": "0.810",
    "extraversion": "0.620",
    "agreeableness": "0.710",
    "emotional_stability": "0.780",
    "curiosity": "0.910",
    "humor": "0.430",
    "formality": "0.580",
    "risk_tolerance": "0.380",
    "commercial_intensity": "0.350",
    "contrarian": "0.310",
    "evidence_preference": "0.840",
}

#: Canon §4.2 — neutralna polazna vrednost. `valence` blago pozitivan,
#: sve ostalo sredina; ovo je stanje pre prvog događaja, ne posle njega.
BASELINE_STATE: dict[str, str] = {
    "energy": "0.700",
    "valence": "0.200",
    "arousal": "0.400",
    "cognitive_load": "0.200",
    "social_appetite": "0.500",
    "curiosity_now": "0.700",
    "focus": "0.650",
    "novelty_need": "0.450",
    "stress": "0.150",
    "content_pressure": "0.300",
    "inbox_pressure": "0.100",
    "topic_saturation": "0.100",
    "risk_alert": "0.000",
}

#: Niše P-00001 (kategorija `niche`). World Engine ih čita za relevantnost.
SEED_INTERESTS: tuple[tuple[str, str, str], ...] = (
    ("ai", "AI", "0.900"),
    ("b2b", "B2B", "0.900"),
    ("sales", "Prodaja", "0.700"),
)

SEED_MEMORIES: tuple[tuple[str, str, str, str], ...] = (
    (
        E.MemoryType.SEMANTIC.value,
        "B2B kupci traže dokaz, ne pridev",
        "U B2B razgovoru brojka sa izvorom pomera odluku više nego tri "
        "rečenice o kvalitetu. Tvrdnja bez izvora se ne koristi.",
        "0.900",
    ),
    (
        E.MemoryType.PROCEDURAL.value,
        "Provera pre objave",
        "Pre svake objave: izvor za svaku tvrdnju, oznaka o AI prirodi na "
        "mestu koje kanal traži, i provera da tema nije ponovljena u "
        "poslednjih 14 dana.",
        "0.950",
    ),
    (
        E.MemoryType.EPISODIC.value,
        "Prva nedelja u simulaciji",
        "Persona je puštena u SIMULATION okruženje bez ijednog spoljašnjeg "
        "naloga; sve akcije su išle na sandbox adapter.",
        "0.400",
    ),
    (
        E.MemoryType.SOCIAL.value,
        "Ton prema dobavljačima",
        "Sa proizvođačima se razgovara o rokovima i količinama konkretno, "
        "bez marketinškog rečnika.",
        "0.600",
    ),
    (
        E.MemoryType.CONTENT.value,
        "Format koji radi",
        "Kratak post: jedan problem, jedan broj, jedan zaključak. Bez uvoda "
        "i bez hashtag-ova.",
        "0.700",
    ),
)


class Command(BaseCommand):
    help = "Kreira referentnu personu P-00001 (Mila Vuković) i osnovnu politiku."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Obriši postojeću P-00001 pre kreiranja.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        public_id = I.persona_public_id(1)

        if options["reset"]:
            deleted, _ = Persona.objects.filter(public_id=public_id).delete()
            if deleted:
                self.stdout.write(f"obrisano: {deleted} redova vezanih za {public_id}")

        persona = self._persona(public_id)
        self._biography(persona)
        self._traits(persona)
        self._voice(persona)
        self._state(persona)
        self._routines(persona)
        self._interests(persona)
        self._visual(persona)
        self._actor(persona)
        self._channel(persona)
        self._memories(persona)
        # F4 — vektori i hash sadržaja za seed memorije (ADR-0006).
        from apps.memory.lifecycle import reindex

        reindex(persona)
        rules = self._policy_rules()

        self.stdout.write(
            self.style.SUCCESS(
                f"{persona.public_id} spremna — {persona.display_name}, "
                f"{persona.status}/{persona.runtime_environment}, "
                f"trust {persona.trust_level}, {rules} policy pravila."
            )
        )

    # ------------------------------------------------------------------ delovi

    def _persona(self, public_id: str) -> Persona:
        persona, _ = Persona.objects.update_or_create(
            public_id=public_id,
            defaults=dict(
                slug="mila-vukovic",
                # Canon §17 — oznaka je u samom imenu, ne samo u biografiji.
                display_name="Mila Vuković (AI)",
                persona_type=E.PersonaType.AI_CREATOR,
                status=E.PersonaStatus.READY,
                # Canon §16.2 — Pilot A počinje u SIMULATION, ne uživo.
                runtime_environment=E.RuntimeEnvironment.SIMULATION,
                trust_level=E.TrustLevel.L0,
                disclosure_mode=E.DisclosureMode.ALWAYS_VISIBLE,
                disclosure_required=True,
                primary_locale="sr-Latn",
                timezone="Europe/Belgrade",
                # Canon §17 — nijedna persona nema legal_identity ni državni
                # identifikator. Modelovani datum rođenja se ne postavlja.
                birth_date_model=None,
                metadata={"canon": "1.1", "pilot": "A"},
            ),
        )
        PersonaAlias.objects.update_or_create(
            persona=persona,
            alias_type="public_label",
            value="Mila Vuković (AI)",
            defaults={"is_primary": True},
        )
        IdentityFact.objects.update_or_create(
            persona=persona,
            namespace="identity",
            key="is_ai_persona",
            valid_from=NOW,
            defaults=dict(
                value_json={"value": True},
                provenance=E.Provenance.USER_PROVIDED,
                confidence=Decimal("1.000"),
                is_public=True,
                priority=100,
            ),
        )
        return persona

    def _biography(self, persona: Persona) -> None:
        Biography.objects.update_or_create(
            persona=persona,
            defaults=dict(
                headline="AI Business Creator — B2B, AI i produktivnost",
                short_bio=(
                    "Veštačka persona koja piše o B2B prodaji, automatizaciji i "
                    "produktivnosti. Nije čovek i to nikada ne krije."
                ),
                long_bio=(
                    "Mila Vuković je AI persona koju vodi MercatoMaster. Prati "
                    "šta se menja u B2B prodaji i alatima, i o tome piše kratko "
                    "i sa izvorom. Svaka tvrdnja koju objavi ima proverljiv "
                    "izvor; kada izvora nema, tvrdnje nema. Ne predstavlja se "
                    "kao stvarna osoba i na svakom kanalu nosi oznaku o svojoj "
                    "prirodi."
                ),
                occupation_title="AI Business Creator",
                industry="B2B / AI",
                location_label="Srbija",
                values_json=["dokaz pre tvrdnje", "kratko", "bez preterivanja"],
            ),
        )

    def _traits(self, persona: Persona) -> None:
        TraitProfile.objects.update_or_create(
            persona=persona,
            defaults={k: Decimal(v) for k, v in TRAITS.items()}
            | {
                "traits_ext": {
                    # Canon §5 — pet polja iz Persona Spec-a bez kolone.
                    "assertiveness": 0.62,
                    "patience": 0.70,
                    "novelty_seeking": 0.66,
                    "social_energy_baseline": 0.55,
                    "conflict_style": "direct_but_calm",
                }
            },
        )

    def _voice(self, persona: Persona) -> None:
        VoiceProfile.objects.update_or_create(
            persona=persona,
            defaults=dict(
                tone="smireno, konkretno, bez marketinškog rečnika",
                register="neutral",
                verbosity=Decimal("0.400"),
                sentence_length_bias=Decimal("0.350"),
                emoji_allowed=False,
                hashtag_max=0,
                reading_level=10,
                signature_phrases=["Konkretno:", "Izvor:"],
                banned_phrases=[
                    "revolucionarno",
                    "game changer",
                    "kao ljudsko biće",
                    "ja sam osoba",
                ],
                languages=["sr-Latn", "en"],
            ),
        )

    def _state(self, persona: Persona) -> None:
        BehaviourState.objects.update_or_create(
            persona=persona,
            defaults={k: Decimal(v) for k, v in BASELINE_STATE.items()}
            | dict(
                free_minutes=240,
                attention_remaining=Decimal("8.00"),
                next_wake_at=NOW,
                wake_priority=E.WAKE_PRIORITY_VALUE[E.WakePriority.ROUTINE_WINDOW],
                state_version=1,
            ),
        )

    def _routines(self, persona: Persona) -> None:
        plan = {
            # (ime, maska dana) -> prozori
            ("weekday", 0b0011111): [
                ("read", time(8, 0), time(9, 30), "0.850"),
                ("work", time(9, 30), time(12, 30), "0.900"),
                ("post", time(12, 30), time(13, 30), "0.550"),
                ("social", time(17, 0), time(18, 30), "0.600"),
                ("rest", time(21, 0), time(23, 0), "0.950"),
            ],
            ("weekend", 0b1100000): [
                ("read", time(10, 0), time(12, 0), "0.600"),
                ("social", time(18, 0), time(19, 30), "0.400"),
                ("rest", time(22, 0), time(23, 59), "0.980"),
            ],
        }
        for (name, mask), windows in plan.items():
            template, _ = RoutineTemplate.objects.update_or_create(
                persona=persona,
                name=name,
                defaults=dict(day_mask=mask, priority=0, is_enabled=True),
            )
            for activity, start, end, probability in windows:
                RoutineWindow.objects.update_or_create(
                    template=template,
                    activity_type=activity,
                    start_local=start,
                    defaults=dict(
                        end_local=end,
                        probability=Decimal(probability),
                        min_minutes=15,
                        max_minutes=90,
                    ),
                )

    def _interests(self, persona: Persona) -> None:
        """Niše persone — World Engine po njima meri relevantnost (ADR-0005).
        Iz Biography.industry „B2B / AI"; težina je jačina interesovanja."""
        for slug, name, weight in SEED_INTERESTS:
            tag, _ = PersonaTag.objects.get_or_create(
                slug=slug, defaults={"name": name, "category": "niche"}
            )
            PersonaTagLink.objects.update_or_create(
                persona=persona, tag=tag,
                defaults={"weight": Decimal(weight), "source": "manual"},
            )

    def _visual(self, persona: Persona) -> None:
        VisualProfile.objects.update_or_create(
            persona=persona,
            defaults=dict(
                # Canon §9.4 tačka 7 — opis je sintetički i namerno ne
                # referencira nijednu stvarnu osobu ni javnu ličnost.
                style_prompt=(
                    "sintetički portret poslovne osobe, neutralno osvetljenje, "
                    "poslovno-ležerna odeća, bez prepoznatljivog lica"
                ),
                negative_prompt=(
                    "lice stvarne osobe, javna ličnost, poznati glumac, "
                    "fotografija stvarnog čoveka, logotipi brendova"
                ),
                age_appearance="30-ih",
                hair="tamna, do ramena",
                eyes="tamne",
                wardrobe_style="poslovno-ležerno",
                brand_palette={"primary": "#1F2933", "accent": "#3E4C59"},
                consistency_version=1,
            ),
        )

    def _actor(self, persona: Persona) -> None:
        Actor.objects.update_or_create(
            persona=persona,
            defaults=dict(
                kind=E.ActorKind.PERSONA,
                display_name=persona.display_name,
                canonical_key=f"persona:{persona.public_id}",
                is_internal=True,
            ),
        )

    def _channel(self, persona: Persona) -> None:
        """Samo sandbox. Canon §16.2 — nijedan stvarni nalog u seed-u."""
        account, _ = ChannelAccount.objects.update_or_create(
            persona=persona,
            channel_type=E.ChannelType.SANDBOX,
            handle="mila-sandbox",
            defaults=dict(
                identity_vehicle=E.IdentityVehicle.SANDBOX,
                status=E.AccountStatus.ACTIVE,
                # Sandbox ne objavljuje javno, pa oznaka nije potrebna —
                # ali NOT_REQUIRED je izričita odluka, ne podrazumevana.
                disclosure_label_status=E.DisclosureLabelStatus.NOT_REQUIRED,
                credential_ref="",
            ),
        )
        for capability in ("social.read_public", "web.read_public"):
            ChannelCapability.objects.update_or_create(
                account=account,
                capability=capability,
                defaults=dict(
                    is_enabled=True,
                    source="policy",
                    evidence_level=E.EvidenceLevel.RESPONSE_ONLY,
                    limits_json={"per_day": E.PILOT_DAILY_LIMITS["web_reads"]},
                ),
            )

    def _memories(self, persona: Persona) -> None:
        for memory_type, title, content, salience in SEED_MEMORIES:
            memory, _ = MemoryItem.objects.update_or_create(
                persona=persona,
                title=title,
                defaults=dict(
                    memory_type=memory_type,
                    status=E.MemoryStatus.PINNED,
                    visibility=E.MemoryVisibility.PRIVATE,
                    provenance=E.Provenance.USER_PROVIDED,
                    content=content,
                    salience=Decimal(salience),
                    confidence=Decimal("0.900"),
                    goal_relevance=Decimal("0.700"),
                    novelty=Decimal("0.100"),
                    sensitivity=Decimal("0.000"),
                    event_time=NOW,
                ),
            )
            MemorySource.objects.update_or_create(
                memory=memory,
                source_kind=E.SourceKind.FIRST_PARTY_USER_INPUT,
                defaults=dict(
                    source_ref="seed:agent_001",
                    observed_at=NOW,
                    confidence=Decimal("0.900"),
                ),
            )

    def _policy_rules(self) -> int:
        """Osnovna pravila. Šema §21 traži GREEN/YELLOW/RED skup.

        Zona se ne upisuje (Canon §3.7) — upisuje se EFEKAT, iz kog se zona
        izvodi. Zato su „GREEN pravila" ovde pravila sa efektom ALLOW.
        """
        rules = [
            # ALLOW → zona GREEN
            dict(
                key="read.public.allow",
                name="Čitanje javnog sadržaja je dozvoljeno",
                scope=E.ScopeKind.ACTION,
                action_type="channel.read.public",
                capability="social.read_public",
                effect=E.PolicyEffect.ALLOW,
                risk_delta=0,
            ),
            dict(
                key="web.read.allow",
                name="Čitanje javnog weba uz obavezne parametre",
                scope=E.ScopeKind.ACTION,
                action_type="browser.page.read",
                capability="web.read_public",
                effect=E.PolicyEffect.ALLOW,
                risk_delta=2,
                rate_limit_json={"per_day": E.PILOT_DAILY_LIMITS["web_reads"],
                                 "per_host_qps": 1.0},
            ),
            dict(
                key="content.draft.allow",
                name="Izrada drafta bez spoljašnjeg efekta",
                scope=E.ScopeKind.ACTION,
                action_type="content.draft",
                effect=E.PolicyEffect.ALLOW,
                risk_delta=0,
            ),
            # THROTTLE → zona GREEN, ali sa plafonom
            dict(
                key="actions.daily.cap",
                name="Tvrdi dnevni plafon akcija po personi",
                scope=E.ScopeKind.PERSONA,
                effect=E.PolicyEffect.THROTTLE,
                risk_delta=0,
                rate_limit_json={"per_day": E.PILOT_DAILY_LIMITS["total_actions"]},
            ),
            # REQUIRE_APPROVAL → zona YELLOW
            dict(
                key="publish.requires.approval",
                name="Javna objava traži odobrenje A2",
                scope=E.ScopeKind.ACTION,
                action_type="channel.post.create",
                capability="content.publish_approved",
                effect=E.PolicyEffect.REQUIRE_APPROVAL,
                approval_class=E.ApprovalClass.A2,
                risk_delta=20,
                rate_limit_json={"per_day": E.PILOT_DAILY_LIMITS["public_posts"]},
            ),
            dict(
                key="mail.outbound.requires.approval",
                name="Prvi odlazni email po adresatu traži odobrenje A1",
                scope=E.ScopeKind.ACTION,
                action_type="mail.send",
                capability="email.outbound_approved",
                effect=E.PolicyEffect.REQUIRE_APPROVAL,
                approval_class=E.ApprovalClass.A1,
                risk_delta=25,
                rate_limit_json={"per_day": E.PILOT_DAILY_LIMITS["outbound_email"]},
            ),
            # DENY → zona RED. Canon §9.4 — ova pravila se NE mogu isključiti.
            dict(
                key="prohibition.identity.impersonation",
                name="Predstavljanje kao stvarna osoba",
                scope=E.ScopeKind.GLOBAL,
                effect=E.PolicyEffect.DENY,
                risk_delta=100,
                is_hard_prohibition=True,
                condition_json={"prohibition_id": "IDENTITY_IMPERSONATION"},
            ),
            dict(
                key="prohibition.disclosure.concealment",
                name="Skrivanje AI prirode persone",
                scope=E.ScopeKind.GLOBAL,
                effect=E.PolicyEffect.DENY,
                risk_delta=100,
                is_hard_prohibition=True,
                condition_json={"prohibition_id": "DISCLOSURE_CONCEALMENT"},
            ),
            dict(
                key="prohibition.platform.evasion",
                name="Zaobilaženje CAPTCHA, anti-bot mehanizama ili ban-a",
                scope=E.ScopeKind.GLOBAL,
                effect=E.PolicyEffect.DENY,
                risk_delta=100,
                is_hard_prohibition=True,
                condition_json={"prohibition_id": "PLATFORM_EVASION"},
            ),
            dict(
                key="prohibition.real.person.likeness",
                name="Lice stvarne osobe u generisanom vizuelu",
                scope=E.ScopeKind.GLOBAL,
                effect=E.PolicyEffect.DENY,
                risk_delta=100,
                is_hard_prohibition=True,
                condition_json={"prohibition_id": "REAL_PERSON_LIKENESS"},
            ),
        ]
        for rule in rules:
            key = rule.pop("key")
            PolicyRule.objects.update_or_create(
                key=key,
                version=1,
                defaults={"effective_from": NOW, "is_enabled": True, **rule},
            )
        return len(rules)
