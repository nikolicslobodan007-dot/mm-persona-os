"""Rutiranje modela, trag promptova i potrošnja. Canon v1.1 §1, §13.2.

Šema v0.1 ovaj app nije imala — Canon §1 ga uvodi kao dvanaesti. Posledica
je da ovde nema „odstupanja od šeme", nego samo obaveza da se poštuju tri
pravila koja Canon postavlja drugde:

  - Trošak se meri u EUR centima i knjiži u `observability.CostLedger`
    (§13.1). `LLMUsage` je tehnički zapis poziva; novčani zapis je tamo.
  - Prompt se ne čuva u bazi kao tekst. Čuvaju se hash i referenca na
    object storage, jer prompt sadrži memorijski kontekst persone, a
    curenje memorije između persona je automatski NO-GO uslov (§16.4).
  - LLM ne menja stanje persone (§4.3). Model predlaže akciju; stanje menja
    reducer, na osnovu ishoda. Zato ovde nema nijedne veze ka
    `BehaviourState`.
"""

from __future__ import annotations

from django.db import models

from common import enums as E
from common.models import JSON_DICT, UUIDModel, unit_interval


class LLMRoute(UUIDModel):
    """Koji model za koju svrhu, sa redosledom otpornosti.

    `data_training_allowed` stoji ovde, a ne u dokumentaciji, zato što je
    to uslov upotrebe a ne beleška: model koji provajder sme da trenira na
    našim podacima ne sme dobiti prompt koji nosi memoriju persone ni
    poslovne podatke dobavljača, bez obzira na to koliko je jeftin.
    """

    purpose = models.CharField(max_length=24, choices=E.LLMPurpose.choices())
    name = models.CharField(max_length=120)
    provider = models.CharField(max_length=80)
    model_key = models.CharField(max_length=160)
    priority = models.SmallIntegerField(
        default=0, help_text="Manji broj = prvi izbor; sledeći je fallback."
    )
    is_enabled = models.BooleanField(default=True)

    context_window = models.PositiveIntegerField(null=True, blank=True)
    max_output_tokens = models.PositiveIntegerField(null=True, blank=True)
    temperature = unit_interval(default=0.7)
    timeout_seconds = models.PositiveSmallIntegerField(default=60)

    # Cena u EUR mikrocentima po 1000 tokena — ceo broj, bez float-a (§13.1).
    input_price_micro_eur_per_1k = models.BigIntegerField(default=0)
    output_price_micro_eur_per_1k = models.BigIntegerField(default=0)

    data_training_allowed = models.BooleanField(
        default=False,
        help_text="True samo ako provajder izričito NE trenira na našim podacima.",
    )
    is_openai_compatible = models.BooleanField(default=True)
    base_url = models.CharField(
        max_length=300, blank=True,
        help_text="Adresa API-ja provajdera. Nije tajna, pa sme u bazu; prazno "
                  "znači „uzmi iz podešavanja” (ADR-0026).")
    quota_json = JSON_DICT(help_text="RPM, TPM, dnevni limit, datum isteka besplatne kvote.")
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "llm_gateway_route"
        indexes = [models.Index(fields=["purpose", "is_enabled", "priority"])]
        constraints = [
            models.UniqueConstraint(
                fields=["purpose", "provider", "model_key"], name="llm_route_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(temperature__gte=0) & models.Q(temperature__lte=1),
                name="llm_route_temperature_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(input_price_micro_eur_per_1k__gte=0)
                & models.Q(output_price_micro_eur_per_1k__gte=0),
                name="llm_route_prices_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.purpose}:{self.provider}/{self.model_key}"


class PromptRecord(UUIDModel):
    """Trag jednog poziva modela — bez teksta prompta u bazi.

    `prompt_ref` i `response_ref` su ključevi u object storage-u sa
    sopstvenom retencijom. U bazi ostaju hash-evi, pa se može dokazati da
    je određeni izlaz nastao iz određenog ulaza, a da se sam sadržaj može
    obrisati kad politika to traži.
    """

    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="prompt_records",
    )
    run = models.ForeignKey(
        "orchestration.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prompt_records",
    )
    plan_step = models.ForeignKey(
        "orchestration.PlanStep",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prompt_records",
    )
    context_pack = models.ForeignKey(
        "memory.MemoryContextPack",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prompt_records",
    )
    route = models.ForeignKey(
        LLMRoute, on_delete=models.PROTECT, related_name="prompt_records"
    )
    purpose = models.CharField(max_length=24, choices=E.LLMPurpose.choices())

    system_hash = models.CharField(max_length=64, blank=True)
    prompt_hash = models.CharField(max_length=64)
    response_hash = models.CharField(max_length=64, blank=True)
    prompt_ref = models.CharField(max_length=512, blank=True)
    response_ref = models.CharField(max_length=512, blank=True)

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    finish_reason = models.CharField(max_length=40, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "llm_gateway_prompt_record"
        indexes = [
            models.Index(fields=["run", "started_at"]),
            models.Index(fields=["persona", "purpose", "started_at"]),
            models.Index(fields=["prompt_hash"]),
        ]

    def __str__(self) -> str:
        return f"{self.purpose}@{self.route_id} {self.finish_reason or '…'}"


class LLMUsage(UUIDModel):
    """Tokeni i izvedeni trošak jednog poziva.

    Odvojeno od `PromptRecord` jer jedan poziv može imati više naplativih
    stavki (ulaz, izlaz, keširani ulaz, reasoning tokeni), a i zato što se
    trošak ponekad sazna tek naknadno, iz provajderovog izveštaja.
    """

    prompt_record = models.ForeignKey(
        PromptRecord, on_delete=models.CASCADE, related_name="usage"
    )
    route = models.ForeignKey(
        LLMRoute, on_delete=models.PROTECT, related_name="usage"
    )
    cost_bucket = models.CharField(
        max_length=24, choices=E.CostBucket.choices(), default=E.CostBucket.LLM
    )
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cached_input_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(default=0)
    amount_eur_cents = models.BigIntegerField(default=0)
    is_estimated = models.BooleanField(
        default=True, help_text="False kada je potvrđeno iz provajderovog izveštaja."
    )
    cost_entry = models.ForeignKey(
        "observability.CostLedger",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="llm_usage",
    )
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = "llm_gateway_usage"
        indexes = [
            models.Index(fields=["route", "recorded_at"]),
            models.Index(fields=["recorded_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_eur_cents__gte=0),
                name="llm_usage_amount_non_negative",
            ),
            models.UniqueConstraint(
                fields=["prompt_record", "cost_bucket"],
                name="llm_usage_unique_bucket_per_call",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.input_tokens}+{self.output_tokens} tok → {self.amount_eur_cents}c"


class AgentCredential(UUIDModel):
    """Ključ jednog agenta kod jednog provajdera — **referenca, ne ključ**. ADR-0026.

    U bazi nikada ne stoji sam ključ. Stoji `file:` ili `env:` referenca, a
    vrednost živi u fajlu sa pravima 0600, van baze i van `pg_dump`-a. Zato
    postoji i CHECK: red koji ne izgleda kao referenca ne može ni da uđe.

    Otisak (`fingerprint`) je poslednja četiri znaka ključa — dovoljno da čovek
    prepozna koji je ključ postavio, premalo da išta otključa.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="llm_credentials"
    )
    provider = models.CharField(max_length=80)
    credential_ref = models.CharField(max_length=512)
    label = models.CharField(max_length=120, blank=True)
    fingerprint = models.CharField(max_length=8, blank=True)
    set_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "llm_gateway_agent_credential"
        constraints = [
            models.UniqueConstraint(fields=["persona", "provider"],
                                    name="agent_credential_unique"),
            models.CheckConstraint(
                condition=models.Q(credential_ref__regex=r"^(env|file):."),
                name="agent_credential_is_reference_only",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.persona_id}:{self.provider}"


class AgentRoute(UUIDModel):
    """Koji model ovaj agent koristi za koju svrhu. ADR-0026.

    Firmina ruta ostaje zajednička polazna tačka; agentova je ispred nje.
    Time jedan agent može da piše nacrte jeftinim modelom, a da odgovore na
    poštu i dalje piše onaj koji je za to izmeren.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="llm_routes"
    )
    purpose = models.CharField(max_length=24, choices=E.LLMPurpose.choices())
    route = models.ForeignKey(LLMRoute, on_delete=models.CASCADE,
                              related_name="agent_routes")
    priority = models.SmallIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "llm_gateway_agent_route"
        indexes = [models.Index(fields=["persona", "purpose", "is_enabled", "priority"])]
        constraints = [
            models.UniqueConstraint(fields=["persona", "purpose", "route"],
                                    name="agent_route_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.persona_id}:{self.purpose}→{self.route_id}"
