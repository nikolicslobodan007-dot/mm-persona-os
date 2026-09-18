"""Društveni graf. Canon v1.1 §1.

Odstupanje od šeme v0.1: enum-i su preseljeni u `common/enums.py`.
Canon §20 tačka 3 kaže da enum van tog fajla ne postoji, a
`tools/canon_lint.py` to sprovodi nad svakim fajlom u repou.

`Actor` je jedinstvena apstrakcija za personu, realan kontakt i organizaciju.
Postoji da izvršne i audit tabele mogu da referenciraju spoljne učesnike
bez pretvaranja tih učesnika u persone.
"""

from __future__ import annotations

from django.db import models

from common import enums as E
from common.models import JSON_DICT, UUIDModel, unit_interval


class Actor(UUIDModel):
    """Jedan red po učesniku. Persona ima najviše jedan Actor zapis."""

    kind = models.CharField(max_length=24, choices=E.ActorKind.choices())
    persona = models.OneToOneField(
        "personas.Persona",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="actor",
        help_text="Popunjeno samo za kind=PERSONA.",
    )
    display_name = models.CharField(max_length=180)
    canonical_key = models.CharField(
        max_length=220, null=True, blank=True, help_text="Ključ za dedupe."
    )
    is_internal = models.BooleanField(default=False)
    metadata = JSON_DICT()

    class Meta:
        db_table = "social_graph_actor"
        indexes = [models.Index(fields=["kind", "display_name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["canonical_key"],
                condition=models.Q(canonical_key__isnull=False),
                name="actor_unique_canonical_key",
            ),
            models.CheckConstraint(
                # Persona vezu sme da ima samo PERSONA actor i obrnuto.
                condition=(
                    models.Q(kind=E.ActorKind.PERSONA.value, persona__isnull=False)
                    | ~models.Q(kind=E.ActorKind.PERSONA.value) & models.Q(persona__isnull=True)
                ),
                name="actor_persona_only_for_persona_kind",
            ),
        ]


class Relationship(UUIDModel):
    """Stanje odnosa između dva Actor-a. Istorija je u RelationshipEvent."""

    source = models.ForeignKey(
        Actor, on_delete=models.CASCADE, related_name="outgoing_relationships"
    )
    target = models.ForeignKey(
        Actor, on_delete=models.CASCADE, related_name="incoming_relationships"
    )
    relation_type = models.CharField(max_length=24, choices=E.RelationshipType.choices())
    strength = unit_interval()
    trust = unit_interval()
    status = models.CharField(
        max_length=24,
        choices=E.RelationshipStatus.choices(),
        default=E.RelationshipStatus.ACTIVE,
    )
    started_at = models.DateTimeField()
    last_interaction_at = models.DateTimeField(null=True, blank=True)
    context_json = JSON_DICT()

    class Meta:
        db_table = "social_graph_relationship"
        indexes = [
            models.Index(fields=["source", "relation_type", "status"]),
            models.Index(fields=["target", "relation_type", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target", "relation_type"],
                name="relationship_unique_triple",
            ),
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")),
                name="relationship_no_self",
            ),
            models.CheckConstraint(
                condition=models.Q(strength__gte=0) & models.Q(strength__lte=1),
                name="relationship_strength_unit",
            ),
            models.CheckConstraint(
                condition=models.Q(trust__gte=0) & models.Q(trust__lte=1),
                name="relationship_trust_unit",
            ),
        ]


class RelationshipEvent(UUIDModel):
    """Append-only istorija promena odnosa."""

    relationship = models.ForeignKey(
        Relationship, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=48)
    delta_strength = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    delta_trust = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    source_action = models.ForeignKey(
        "orchestration.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relationship_events",
    )
    occurred_at = models.DateTimeField()
    payload = JSON_DICT()

    class Meta:
        db_table = "social_graph_relationship_event"
        indexes = [models.Index(fields=["relationship", "occurred_at"])]
