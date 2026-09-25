"""Persona core, biografija i identitetske tvrdnje.

Canon v1.1 §1 (app mapa), §3.1–3.4 (status, okruženje, tip, oznaka), §3.11 (poverenje).

Odstupanja od Database & Django Schema v0.1, po pravilu prvenstva iz Canon §0:
  - `status` dobija READY i DEGRADED (Canon §3.1); šema ih nije imala.
  - `runtime_environment` je NOVO i ortogonalno statusu (Canon §3.2) —
    persona može biti ACTIVE u SIMULATION.
  - `trust_level` je NOVO (Canon §3.11); L3 i L4 se ne mogu dodeliti.
  - `PersonaType.BRAND_ASSISTANT` iz šeme ne postoji; Canon ima
    BRAND_AGENT i ASSISTANT kao dva odvojena tipa.
  - `DisclosureMode` vrednosti su Canon-ove; nijedna ne skriva AI prirodu.
  - Biografija, LifeEvent i IdentityFact su iz app-a `identity` (šema)
    prebačeni ovde: Canon §1 nema app `identity`, a `visuals` drži samo
    vizuelni identitet.
  - `TraitProfile` je iz app-a za ponašanje (šema) prebačen ovde i proširen
    sa 11 na kanonskih 12 osobina (Canon §5). `verbosity` ispada iz osobina.
  - `VoiceProfile` je NOV (Canon §1, §5). Šema ga nije imala, pa je stil
    bio pomešan sa karakterom — a voice consistency ima sopstveni prag
    u kapijama pilota (Canon §16.3).
"""

from __future__ import annotations

from django.db import models

from common import enums as E
from common.models import JSON_DICT, JSON_LIST, UUIDModel, unit_interval


class Persona(UUIDModel):
    """Agregatni koren. Canon §3.1–3.4, §3.11.

    Ne nosi ni biografiju ni provider podatke — to su odvojene tabele,
    da bi `Persona` ostala jeftina za scheduler koji je čita stalno.
    """

    public_id = models.CharField(max_length=24, unique=True)  # P-00001
    slug = models.SlugField(max_length=120, unique=True)
    display_name = models.CharField(max_length=160)

    persona_type = models.CharField(max_length=32, choices=E.PersonaType.choices())
    status = models.CharField(
        max_length=24, choices=E.PersonaStatus.choices(), default=E.PersonaStatus.DRAFT
    )
    runtime_environment = models.CharField(
        max_length=24,
        choices=E.RuntimeEnvironment.choices(),
        default=E.RuntimeEnvironment.SIMULATION,
    )
    trust_level = models.CharField(
        max_length=4, choices=E.TrustLevel.choices(), default=E.TrustLevel.L0
    )
    disclosure_mode = models.CharField(
        max_length=32, choices=E.DisclosureMode.choices()
    )
    disclosure_required = models.BooleanField(default=True)

    primary_locale = models.CharField(max_length=16)  # sr-Latn, en, it
    timezone = models.CharField(max_length=64)  # IANA
    birth_date_model = models.DateField(
        null=True, blank=True, help_text="Modelovana starost; nije državni identitet."
    )

    activated_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)  # optimistic locking
    metadata = JSON_DICT()
    config_ext = JSON_DICT(
        help_text=(
            "Canon §5, *_ext obrazac: polja iz Persona Spec-a koja nemaju kolonu. "
            "JSONB bez JSON Scheme nije dozvoljen."
        )
    )

    class Meta:
        db_table = "personas_persona"
        indexes = [
            models.Index(fields=["status", "persona_type"]),
            models.Index(fields=["disclosure_mode"]),
            models.Index(fields=["runtime_environment", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                # Canon §3.1 — ARCHIVED bez datuma arhiviranja je nekonzistentan zapis.
                condition=~models.Q(status=E.PersonaStatus.ARCHIVED.value)
                | models.Q(archived_at__isnull=False),
                name="persona_archived_has_timestamp",
            ),
            models.CheckConstraint(
                # Canon §3.11 (v1.1, A-08) — L3 i L4 su rezervisani dok ADR
                # ne imenuje kanal na kom se odlazni prvi kontakt izvršava.
                condition=models.Q(
                    trust_level__in=E.ASSIGNABLE_TRUST_LEVEL_VALUES
                ),
                name="persona_trust_level_assignable",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} {self.display_name}"


class PersonaAlias(UUIDModel):
    """Alternativna imena i handle-ovi, sa eksplicitnim tipom."""

    persona = models.ForeignKey(
        Persona, on_delete=models.CASCADE, related_name="aliases"
    )
    alias_type = models.CharField(max_length=32)  # nickname/handle/public_label
    value = models.CharField(max_length=160)
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "personas_alias"
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "alias_type", "value"], name="alias_unique_value"
            ),
            models.UniqueConstraint(
                fields=["persona", "alias_type"],
                condition=models.Q(is_primary=True),
                name="alias_one_primary_per_type",
            ),
        ]


class PersonaTag(UUIDModel):
    """Taksonomija niša, jezika i kohorti."""

    name = models.CharField(max_length=80, unique=True)
    category = models.CharField(max_length=40)  # niche/language/cohort
    slug = models.SlugField(max_length=100, unique=True)

    class Meta:
        db_table = "personas_tag"
        indexes = [models.Index(fields=["category", "slug"])]


class PersonaTagLink(UUIDModel):
    """M2M kroz eksplicitnu tabelu — zbog težine i izvora oznake."""

    persona = models.ForeignKey(
        Persona, on_delete=models.CASCADE, related_name="tag_links"
    )
    tag = models.ForeignKey(
        PersonaTag, on_delete=models.CASCADE, related_name="persona_links"
    )
    weight = unit_interval(default=1)
    source = models.CharField(max_length=32)  # manual/generated/learned

    class Meta:
        db_table = "personas_tag_link"
        constraints = [
            models.UniqueConstraint(fields=["persona", "tag"], name="tag_link_unique"),
            models.CheckConstraint(
                condition=models.Q(weight__gte=0) & models.Q(weight__lte=1),
                name="tag_link_weight_unit",
            ),
        ]


class Biography(models.Model):
    """Stabilna priča persone — odvojena od kratkoročne memorije."""

    persona = models.OneToOneField(
        Persona, on_delete=models.CASCADE, primary_key=True, related_name="biography"
    )
    headline = models.CharField(max_length=220, blank=True)
    short_bio = models.TextField()
    long_bio = models.TextField()
    occupation_title = models.CharField(max_length=160, blank=True)
    industry = models.CharField(max_length=120, blank=True)
    education_summary = models.TextField(blank=True)
    location_label = models.CharField(
        max_length=160, blank=True, help_text="Modelovana lokacija, ne tačna adresa."
    )
    values_json = JSON_LIST()
    story_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "personas_biography"
        indexes = [
            models.Index(fields=["occupation_title"]),
            models.Index(fields=["industry"]),
        ]


class LifeEvent(UUIDModel):
    """Hronološki događaj koji persona sme da referencira u sadržaju."""

    persona = models.ForeignKey(
        Persona, on_delete=models.CASCADE, related_name="life_events"
    )
    event_date = models.DateField(null=True, blank=True)
    year = models.SmallIntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=48)  # education/job/move/travel/project
    title = models.CharField(max_length=220)
    description = models.TextField()
    confidence = unit_interval()
    is_public = models.BooleanField(default=False)
    provenance = models.CharField(
        max_length=24, choices=E.Provenance.choices(), default=E.Provenance.USER_PROVIDED
    )

    class Meta:
        db_table = "personas_life_event"
        indexes = [
            models.Index(fields=["persona", "event_date"]),
            models.Index(fields=["persona", "event_type"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=1),
                name="life_event_confidence_unit",
            )
        ]


class IdentityFact(UUIDModel):
    """Atomizovana tvrdnja — provera konzistentnosti odgovora.

    Canon §10.4: `provenance` zamenjuje slobodno polje `source` iz šeme,
    jer se INFERRED nikada ne sme pojaviti u javnom izlazu.
    """

    persona = models.ForeignKey(
        Persona, on_delete=models.CASCADE, related_name="identity_facts"
    )
    namespace = models.CharField(max_length=64)  # identity/preference/history
    key = models.CharField(max_length=120)
    value_json = JSON_DICT()
    provenance = models.CharField(
        max_length=24, choices=E.Provenance.choices(), default=E.Provenance.USER_PROVIDED
    )
    confidence = unit_interval(default=1)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    is_public = models.BooleanField(default=False)
    priority = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "personas_identity_fact"
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "namespace", "key", "valid_from"],
                name="identity_fact_unique",
            )
        ]
        indexes = [models.Index(fields=["persona", "namespace", "key"])]


#: Canon §5 — kanonskih 12 traits. Poreklo je Agent 001 spec, ne Persona Spec:
#: jedine su koje imaju i definiciju i stvarnu vrednost u referentnoj personi.
CANONICAL_TRAITS: tuple[str, ...] = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "emotional_stability",
    "curiosity",
    "humor",
    "formality",
    "risk_tolerance",
    "commercial_intensity",
    "contrarian",
    "evidence_preference",
)


class TraitProfile(models.Model):
    """Dvanaest trajnih osobina. Canon §5.

    Odstupanja od šeme v0.1: šema je imala 11 kolona i među njima
    `verbosity`. Canon §5 kaže da `verbosity` nije osobina nego stilsko
    svojstvo i seli ga u `VoiceProfile`; umesto njega ulaze
    `commercial_intensity`, `contrarian` i `evidence_preference`.

    Pet polja iz Persona Spec-a (`assertiveness`, `patience`,
    `novelty_seeking`, `social_energy_baseline`, `conflict_style`) NAMERNO
    nemaju kolonu — žive u `traits_ext` i promovišu se tek kada neka
    formula počne da ih čita.
    """

    persona = models.OneToOneField(
        Persona,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="trait_profile",
    )

    openness = unit_interval()
    conscientiousness = unit_interval()
    extraversion = unit_interval()
    agreeableness = unit_interval()
    emotional_stability = unit_interval()
    curiosity = unit_interval(
        help_text="Trajna dispozicija; trenutna vrednost je BehaviourState.curiosity_now."
    )
    humor = unit_interval()
    formality = unit_interval()
    risk_tolerance = unit_interval()
    commercial_intensity = unit_interval()
    contrarian = unit_interval()
    evidence_preference = unit_interval()

    traits_ext = JSON_DICT(help_text="Canon §5 — uz JSON Schema validaciju.")
    trait_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "personas_trait_profile"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(**{f"{t}__gte": 0}) & models.Q(**{f"{t}__lte": 1}),
                name=f"trait_{t}_unit",
            )
            for t in CANONICAL_TRAITS
        ]

    def __str__(self) -> str:
        return f"traits<{self.persona_id}> v{self.trait_version}"


class VoiceProfile(models.Model):
    """Kako persona zvuči. Canon §1, §5.

    Odvojeno od `TraitProfile` jer se stil menja češće od karaktera i jer
    voice consistency ima sopstveni prag u kapijama pilota (Canon §16.3).
    """

    persona = models.OneToOneField(
        Persona,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="voice_profile",
    )
    tone = models.CharField(max_length=120)
    register = models.CharField(max_length=64)  # formal/neutral/casual
    verbosity = unit_interval(help_text="Canon §5: stil, ne osobina.")
    sentence_length_bias = unit_interval(default=0.5)
    emoji_allowed = models.BooleanField(default=False)
    hashtag_max = models.SmallIntegerField(default=0)
    reading_level = models.SmallIntegerField(null=True, blank=True)
    signature_phrases = JSON_LIST()
    banned_phrases = JSON_LIST()
    languages = JSON_LIST()
    style_ext = JSON_DICT(help_text="Canon §5 — uz JSON Schema validaciju.")
    voice_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "personas_voice_profile"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(verbosity__gte=0) & models.Q(verbosity__lte=1),
                name="voice_verbosity_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(sentence_length_bias__gte=0)
                & models.Q(sentence_length_bias__lte=1),
                name="voice_sentence_length_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(hashtag_max__gte=0) & models.Q(hashtag_max__lte=30),
                name="voice_hashtag_max_range",
            ),
        ]

    def __str__(self) -> str:
        return f"voice<{self.persona_id}> v{self.voice_version}"


# ---------------------------------------------------------------- organizacija (ADR-0017)


class Department(UUIDModel):
    """Sektor korporacije. ADR-0017.

    Organizacija nije ukras: ona kaže ko kome odgovara, ko je za šta zadužen
    i na kom nivou važi pouka urednika. Poverenje (Canon §3.11) je odvojeno —
    šef-agent ne dobija nijednu dozvolu time što je šef.
    """

    code = models.CharField(max_length=32, unique=True)  # SALES, CONTENT, …
    name = models.CharField(max_length=120)
    purpose = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    head = models.ForeignKey(
        Persona, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="heads_departments",
        help_text="Agent koji vodi sektor; odgovornost čoveka time ne prestaje.",
    )
    human_owner = models.CharField(
        max_length=120, blank=True, help_text="Čovek koji odgovara za sektor (user:…)."
    )
    sort_order = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "personas_department"
        indexes = [models.Index(fields=["is_active", "sort_order"])]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class Position(UUIDModel):
    """Radno mesto — posao, ne osoba. ADR-0017."""

    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="positions"
    )
    code = models.CharField(max_length=48, unique=True)
    title = models.CharField(max_length=160)
    specialty = models.CharField(max_length=160, blank=True)
    level = models.CharField(
        max_length=16, choices=E.OrgLevel.choices(), default=E.OrgLevel.MEDIOR
    )
    reports_to = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reports"
    )
    duties = JSON_LIST(help_text="Šta radi, jednom rečenicom po stavci.")
    #: ADR-0037 — šta posao TRAŽI: `[{"capability": …, "level": "L1", "scope": …}]`.
    #: Ovo NIJE dozvola i motor pravila ga ne čita; odluka se i dalje donosi
    #: isključivo po `TrustState` (ADR-0017: radno mesto nije dozvola).
    needs = JSON_LIST(help_text="Šta posao traži da bi se radio — opis, ne dozvola.")
    headcount_max = models.PositiveSmallIntegerField(default=1)
    is_open = models.BooleanField(default=True)

    class Meta:
        db_table = "personas_position"
        indexes = [models.Index(fields=["department", "level"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(headcount_max__gte=1),
                name="position_headcount_min_one",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.title}"


class Assignment(UUIDModel):
    """Ko sedi na kom radnom mestu, i od kada. ADR-0017.

    Istorija se ne briše: raspored koji se završi dobija `ended_at`, pa se
    uvek zna ko je šta radio kad je nešto objavljeno.
    """

    persona = models.ForeignKey(
        Persona, on_delete=models.CASCADE, related_name="assignments"
    )
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name="assignments"
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    is_primary = models.BooleanField(default=True)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        db_table = "personas_assignment"
        indexes = [models.Index(fields=["persona", "ended_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["persona"],
                condition=models.Q(ended_at__isnull=True, is_primary=True),
                name="assignment_one_primary_open",
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(ended_at__gt=models.F("started_at")),
                name="assignment_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.persona_id} → {self.position_id}"


class PersonaDossier(models.Model):
    """Modelovana lična istorija i izgled. ADR-0017.

    Canon §17 ostaje na snazi: ovde nema državnog identiteta — ni matičnog
    broja, ni broja dokumenta, ni tačne adrese. Sve je izmišljeno, dosledno i
    služi da agent zvuči kao ista osoba iz meseca u mesec, i da slika
    odgovara opisu (visina, građa, boja očiju i kose).
    """

    persona = models.OneToOneField(
        Persona, on_delete=models.CASCADE, primary_key=True, related_name="dossier"
    )
    birth_place = models.CharField(max_length=120, blank=True)
    residence = models.CharField(max_length=160, blank=True)
    height_cm = models.SmallIntegerField(null=True, blank=True)
    weight_kg = models.SmallIntegerField(null=True, blank=True)
    build = models.CharField(max_length=48, blank=True)       # vitka, atletska, krupna
    eye_color = models.CharField(max_length=32, blank=True)
    hair_color = models.CharField(max_length=32, blank=True)
    hair_style = models.CharField(max_length=64, blank=True)
    distinguishing_marks = models.CharField(max_length=200, blank=True)
    marital_status = models.CharField(max_length=48, blank=True)
    children = models.PositiveSmallIntegerField(default=0)
    hobbies = JSON_LIST()
    appearance_prompt = models.TextField(
        blank=True, help_text="Opis za generisanje slike; isti lik na svakoj slici."
    )
    dossier_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "personas_dossier"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(height_cm__isnull=True)
                | (models.Q(height_cm__gte=120) & models.Q(height_cm__lte=230)),
                name="dossier_height_range",
            ),
            models.CheckConstraint(
                condition=models.Q(weight_kg__isnull=True)
                | (models.Q(weight_kg__gte=35) & models.Q(weight_kg__lte=250)),
                name="dossier_weight_range",
            ),
        ]

    def __str__(self) -> str:
        return f"dosije<{self.persona_id}> v{self.dossier_version}"
