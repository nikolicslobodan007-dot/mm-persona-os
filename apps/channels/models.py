"""Nalozi po kanalu, capability matrica i adapteri. Canon v1.1 §1, §3.14–3.16, §16.

Odstupanja od šeme v0.1 — ovo su najteže izmene iz Aneksa A:
  - `identity_vehicle` je NOVO (Canon §3.14, v1.1 A-01). Nije stilsko
    pitanje nego uslov pristupa: LinkedIn i Facebook dozvoljavaju samo PAGE.
    Dozvoljeni parovi su u `channels/identity_vehicles.yaml`.
  - `disclosure_label_status` je NOVO (Canon §3.16, v1.1 A-02) i zamenjuje
    slobodni tekst `disclosure_text` kao nosioca odluke. Nalog čiji status
    nije SET ili NOT_REQUIRED ne sme u CONTROLLED_LIVE niti izvršiti ijednu
    `channel.*` akciju.
  - `credential_ref` ostaje samo referenca na secret store; Canon §2 i §17
    zabranjuju tajnu u bazi.
  - `MailMessage` je iz app-a `runtime` (šema) prebačen ovde: Canon §1 daje
    vlasništvo `channels`-u, jer je pošta kanal, a ne runtime.
  - `ChannelAccount` tipa EMAIL dobija pet polja iz Canon §12.8:
    `persona_address`, `sending_domain`, `dkim_selector`, `warmup_started_at`,
    `daily_cap`. Razlog je merljiv, ne stilski: reputacija se kod Gmail-a i
    Microsoft-a agregira na nivou domena i DKIM `d=` potpisa, pa jedna persona
    sa prijavama ruši isporuku svima ostalima — uključujući transakcionu poštu.
  - `status` je enum `AccountStatus`, ne slobodan tekst.
"""

from __future__ import annotations

from django.db import models

from common import enums as E
from common.models import JSON_DICT, JSON_LIST, UUIDModel


class ChannelAccount(UUIDModel):
    """Nalog koji persona ili brend legitimno kontroliše."""

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="channel_accounts"
    )
    channel_type = models.CharField(max_length=24, choices=E.ChannelType.choices())
    identity_vehicle = models.CharField(
        max_length=24, choices=E.IdentityVehicle.choices()
    )
    handle = models.CharField(max_length=180)
    provider_account_id = models.CharField(max_length=220, null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=E.AccountStatus.choices(),
        default=E.AccountStatus.PENDING,
    )

    disclosure_label_status = models.CharField(
        max_length=24,
        choices=E.DisclosureLabelStatus.choices(),
        default=E.DisclosureLabelStatus.REQUIRED_NOT_SET,
    )
    disclosure_text = models.CharField(max_length=280, blank=True)
    disclosure_verified_at = models.DateTimeField(null=True, blank=True)

    named_human_admin = models.CharField(
        max_length=180,
        blank=True,
        help_text="Canon §16 (v1.1, A-03): LinkedIn Page traži imenovanog čoveka.",
    )
    # Canon §12.8 — samo za channel_type=EMAIL.
    persona_address = models.CharField(
        max_length=320, blank=True, help_text="Javna adresa persone; prima poštu."
    )
    sending_domain = models.CharField(
        max_length=253,
        blank=True,
        help_text="Odlazna pošta NIKADA sa primarnog domena kompanije (§12.8).",
    )
    dkim_selector = models.CharField(
        max_length=64, blank=True, help_text="transactional/newsletter/outbound."
    )
    warmup_started_at = models.DateTimeField(null=True, blank=True)
    daily_cap = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Ustaljeni plafon 20–50 po mejlboksu (§12.8)."
    )

    credential_ref = models.CharField(
        max_length=255,
        blank=True,
        help_text="Canon §2, §17 — samo referenca na secret store, nikada tajna.",
    )
    browser_profile = models.ForeignKey(
        "runtime.BrowserProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="channel_accounts",
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "channels_account"
        indexes = [
            models.Index(fields=["persona", "status"]),
            models.Index(fields=["channel_type", "disclosure_label_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["channel_type", "provider_account_id"],
                condition=models.Q(provider_account_id__isnull=False),
                name="channel_account_unique_provider_id",
            ),
            models.UniqueConstraint(
                fields=["persona", "channel_type", "handle"],
                name="channel_account_unique_handle",
            ),
            models.CheckConstraint(
                # Canon §16.2 (v1.1, A-10) — TikTok i YouTube su van opsega;
                # adapteri se ne pišu, pa ni nalozi ne smeju da postoje.
                condition=~models.Q(
                    channel_type__in=E.OUT_OF_SCOPE_CHANNEL_VALUES
                ),
                name="channel_account_no_out_of_scope",
            ),
            models.CheckConstraint(
                # Canon §12.8 — polja odlazne pošte postoje samo na EMAIL nalogu.
                condition=models.Q(channel_type=E.ChannelType.EMAIL.value)
                | (models.Q(sending_domain="") & models.Q(persona_address="")),
                name="channel_account_mail_fields_only_for_email",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.channel_type}:{self.handle}"


class ChannelCapability(UUIDModel):
    """Šta je na ovom nalogu stvarno moguće.

    Canon §12.1: `CAPABILITY_UNAVAILABLE` je validan ishod, ne greška.
    Zato se sposobnost vodi po nalogu, a ne pretpostavlja po tipu kanala.
    """

    account = models.ForeignKey(
        ChannelAccount, on_delete=models.CASCADE, related_name="capabilities"
    )
    capability = models.CharField(max_length=64)
    is_enabled = models.BooleanField(default=False)
    source = models.CharField(max_length=32)  # api/manual/policy
    evidence_level = models.CharField(
        max_length=24, choices=E.EvidenceLevel.choices(), null=True, blank=True
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    limits_json = JSON_DICT()

    class Meta:
        db_table = "channels_capability"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "capability"], name="channel_capability_unique"
            )
        ]


class IntegrationEndpoint(UUIDModel):
    """Konfiguracija provider adaptera — bez ijedne tajne."""

    channel_type = models.CharField(max_length=24, choices=E.ChannelType.choices())
    name = models.CharField(max_length=120)
    base_url = models.TextField(blank=True)
    adapter_key = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    settings_json = JSON_DICT()

    class Meta:
        db_table = "channels_integration_endpoint"
        constraints = [
            models.UniqueConstraint(
                fields=["channel_type", "name"], name="integration_endpoint_unique"
            )
        ]


class MailMessage(UUIDModel):
    """Normalizovana koverta dolazne i odlazne pošte. Canon §1, §12.8.

    Telo poruke je opciono i podleže retenciji — koverta se čuva uvek, jer
    bez nje nema audit traga, a sadržaj se čuva samo onoliko koliko politika
    dozvoljava. `provider_message_id` sa jedinstvenošću po nalogu je ono što
    sprečava da se ista poruka dva puta obradi kao nova.
    """

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.PROTECT, related_name="mail_messages"
    )
    channel_account = models.ForeignKey(
        ChannelAccount, on_delete=models.PROTECT, related_name="mail_messages"
    )
    action = models.ForeignKey(
        "orchestration.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mail_messages",
        help_text="Popunjeno za odlaznu poštu — veza sa policy tragom.",
    )
    direction = models.CharField(max_length=8, choices=E.MailDirection.choices())
    provider_message_id = models.CharField(max_length=220)
    thread_key = models.CharField(max_length=220, blank=True)
    in_reply_to = models.CharField(max_length=220, blank=True)
    from_addr = models.CharField(max_length=320)
    to_addrs = JSON_LIST()
    cc_addrs = JSON_LIST()
    subject = models.CharField(max_length=998, blank=True)
    body_text = models.TextField(
        blank=True, help_text="Podleže politici retencije; koverta se čuva uvek."
    )
    body_retained_until = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    dkim_selector = models.CharField(max_length=64, blank=True)
    unsubscribed = models.BooleanField(
        default=False,
        help_text="Canon §12.8 tačka 6 — odjava kod jedne persone važi za sve.",
    )
    metadata = JSON_DICT(help_text="Podskup zaglavlja; bez tajni.")
    trace_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "channels_mail_message"
        indexes = [
            models.Index(fields=["persona", "thread_key"]),
            models.Index(fields=["received_at"]),
            models.Index(fields=["sent_at"]),
            models.Index(fields=["direction", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["channel_account", "provider_message_id"],
                name="mail_message_unique_provider_id",
            ),
            models.CheckConstraint(
                # Dolazna poruka ima vreme prijema, odlazna vreme slanja.
                condition=models.Q(
                    direction=E.MailDirection.INBOUND.value, received_at__isnull=False
                )
                | models.Q(
                    direction=E.MailDirection.OUTBOUND.value, sent_at__isnull=False
                )
                | models.Q(received_at__isnull=True, sent_at__isnull=True),
                name="mail_message_direction_has_timestamp",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.direction} {self.subject[:48] or self.provider_message_id}"


class SuppressionEntry(UUIDModel):
    """Centralna lista odjava. Canon §12.8 t.6 · ADR-0008.

    Jedna lista za SVE mejlbokseve i SVE persone: odjava kod jedne persone
    važi za sve. Adresa se ne čuva — samo `sha256(normalizovana adresa)`.
    Lista mora da zna da li je adresa odjavljena, ne i koja je; tako lista
    odjava ne postaje baza kontakata.

    `domain_hash` (opciono) odjavljuje ceo domen primaoca (npr. firma koja
    traži da joj niko ne piše). Upisi se ne brišu — odjava je trajna.
    """

    address_hash = models.CharField(max_length=64, blank=True, db_index=True)
    domain_hash = models.CharField(max_length=64, blank=True, db_index=True)
    reason = models.CharField(max_length=24, choices=E.SuppressionReason.choices())
    source = models.CharField(max_length=64, help_text="one_click/link/manual/bounce/…")
    created_by = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "channels_suppression"
        constraints = [
            models.UniqueConstraint(
                fields=["address_hash"], condition=~models.Q(address_hash=""),
                name="suppression_unique_address",
            ),
            models.UniqueConstraint(
                fields=["domain_hash"],
                condition=models.Q(address_hash="") & ~models.Q(domain_hash=""),
                name="suppression_unique_domain",
            ),
            models.CheckConstraint(
                condition=~models.Q(address_hash="") | ~models.Q(domain_hash=""),
                name="suppression_has_target",
            ),
        ]

    def __str__(self) -> str:
        return f"suppression<{(self.address_hash or self.domain_hash)[:12]}> {self.reason}"
