"""Vizuelni identitet i medijski fajlovi. Canon v1.1 §1, §2.2 (IMG- public_id).

Odstupanje od šeme v0.1: `MediaAsset` dobija `public_id` oblika
`IMG-P00001-0047` jer je Canon §2.2 uvrstio MediaAsset među entitete sa
čitljivim identifikatorom. Šema ga je imala samo sa UUID-jem.

`AssetKind` je preseljen u `common/enums.py`: Canon §20 tačka 3 ne
dozvoljava enum van tog fajla, bez obzira na to što ga Canon §3 ne normira.
"""

from __future__ import annotations

from django.db import models

from common import enums as E
from common.models import JSON_DICT, JSON_LIST, UUIDModel


class MediaAsset(UUIDModel):
    """Metapodaci o fajlu u object storage-u; sam fajl je u MinIO/S3."""

    public_id = models.CharField(max_length=32, unique=True)  # IMG-P00001-0047
    persona = models.ForeignKey(
        "personas.Persona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_assets",
    )
    kind = models.CharField(max_length=24, choices=E.AssetKind.choices())
    storage_key = models.CharField(max_length=512, unique=True)
    mime_type = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    origin = models.CharField(max_length=32)  # generated/licensed/user_owned/system
    generation_model = models.CharField(max_length=120, blank=True)
    generation_prompt_hash = models.CharField(max_length=64, blank=True)
    rights_note = models.TextField(blank=True)

    class Meta:
        db_table = "visuals_media_asset"
        indexes = [
            models.Index(fields=["persona", "kind", "created_at"]),
            models.Index(fields=["sha256"]),
        ]


class VisualProfile(models.Model):
    """Opis konzistentnog sintetičkog izgleda — bez imitacije realne osobe."""

    persona = models.OneToOneField(
        "personas.Persona",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="visual_profile",
    )
    style_prompt = models.TextField()
    negative_prompt = models.TextField(blank=True)
    age_appearance = models.CharField(max_length=80, blank=True)
    hair = models.CharField(max_length=120, blank=True)
    eyes = models.CharField(max_length=80, blank=True)
    wardrobe_style = models.CharField(max_length=160, blank=True)
    brand_palette = JSON_DICT()
    reference_asset = models.ForeignKey(
        MediaAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reference_for",
    )
    consistency_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "visuals_visual_profile"


class AssetCollection(UUIDModel):
    """Galerija sa namenom: work, travel, home."""

    persona = models.ForeignKey(
        "personas.Persona", on_delete=models.CASCADE, related_name="asset_collections"
    )
    name = models.CharField(max_length=120)
    purpose = models.CharField(max_length=120, blank=True)
    is_public_pool = models.BooleanField(default=False)

    class Meta:
        db_table = "visuals_asset_collection"
        constraints = [
            models.UniqueConstraint(
                fields=["persona", "name"], name="asset_collection_unique_name"
            )
        ]


class AssetCollectionItem(UUIDModel):
    """Redosled i oznake asseta u kolekciji."""

    collection = models.ForeignKey(
        AssetCollection, on_delete=models.CASCADE, related_name="items"
    )
    asset = models.ForeignKey(
        MediaAsset, on_delete=models.CASCADE, related_name="collection_items"
    )
    position = models.IntegerField()
    labels = JSON_LIST()

    class Meta:
        db_table = "visuals_asset_collection_item"
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "asset"], name="collection_item_unique_asset"
            ),
            models.UniqueConstraint(
                fields=["collection", "position"], name="collection_item_unique_position"
            ),
        ]
