"""ADR-0018 — lik agenta: profilna slika i galerija.

  - bez `IMAGE_ENABLED` se ne zove provajder i ništa se ne upisuje;
  - profilna se pravi jednom i postaje referenca identiteta;
  - svaka sledeća slika ide kroz `edits` sa referencom — isti lik;
  - prompt bez dosijea se odbija, kao i prompt koji traži zabranjeno;
  - svaka slika je označena kao AI i knjižena u troškove;
  - dnevni plafon se poštuje.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from django.core.management import call_command

from api.context import bind
from apps.observability.models import CostLedger
from apps.personas.models import Persona
from apps.visuals import generator, storage
from apps.visuals.models import MediaAsset, VisualProfile
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\n" + b"portret"


@pytest.fixture
def slike(mila, settings, monkeypatch):
    """Generator uključen; provajder i storage lažni."""
    settings.IMAGE_ENABLED = True
    settings.IMAGE_PROVIDER = "openai"
    settings.IMAGE_MODEL = "gpt-image-2"
    settings.IMAGE_PRICE_MICRO_EUR = 35000
    monkeypatch.setenv("OPENAI_API_KEY", "kljuc")
    with bind(actor_id="user:slobodan"):
        call_command("seed_org", "--persona", "P-00001", stdout=io.StringIO())

    calls = []
    files: dict[str, bytes] = {}

    def fake_call(path, fields, image, persona):
        calls.append({"path": path, "fields": fields, "has_image": image is not None,
                      "persona": persona.public_id})
        return PNG + path.encode()

    monkeypatch.setattr(generator, "_call", fake_call)
    monkeypatch.setattr(storage, "put",
                        lambda data, *, key, mime: files.__setitem__(key, data) or key)
    monkeypatch.setattr(storage, "get", lambda key: files[key])
    return calls


def _p():
    return Persona.objects.get(public_id="P-00001")


class TestPortrait:
    def test_disabled_does_nothing(self, slike, settings):
        settings.IMAGE_ENABLED = False
        with bind(actor_id="user:slobodan"), pytest.raises(generator.ImageError) as e:
            generator.make_portrait(_p(), actor="user:slobodan", now=NOW)
        assert e.value.code == "IMAGE_DISABLED"
        assert not slike and MediaAsset.objects.count() == 0

    def test_portrait_becomes_reference_and_is_made_once(self, slike):
        with bind(actor_id="user:slobodan"):
            first = generator.make_portrait(_p(), actor="user:slobodan", now=NOW)
            again = generator.make_portrait(_p(), actor="user:slobodan", now=NOW)
        assert first.asset.pk == again.asset.pk
        assert len(slike) == 1 and slike[0]["path"] == "/generations"
        assert slike[0]["has_image"] is False
        a = first.asset
        assert a.kind == E.AssetKind.FACE_REFERENCE
        assert a.origin == "generated" and a.generation_model == "gpt-image-2"
        assert a.generation_prompt_hash and "AI" in a.rights_note
        assert VisualProfile.objects.get(persona=_p()).reference_asset_id == a.pk
        assert a.public_id.startswith("IMG-P00001-")

    def test_prompt_uses_dossier_and_position(self, slike):
        with bind(actor_id="user:slobodan"):
            r = generator.make_portrait(_p(), actor="user:slobodan", now=NOW)
        assert "tamno smeđa" in r.prompt and "smeđe oči" in r.prompt
        assert "urednik sadržaja" in r.prompt.lower()
        assert "izmišljene osobe" in r.prompt

    def test_no_appearance_no_image(self, slike):
        from apps.personas.models import PersonaDossier

        PersonaDossier.objects.filter(persona=_p()).delete()
        VisualProfile.objects.filter(persona=_p()).delete()
        with bind(actor_id="user:slobodan"), pytest.raises(generator.ImageError) as e:
            generator.make_portrait(_p(), actor="user:slobodan", now=NOW)
        assert e.value.code == "VALIDATION_ERROR"

    def test_cost_is_booked(self, slike):
        with bind(actor_id="user:slobodan"):
            r = generator.make_portrait(_p(), actor="user:slobodan", now=NOW)
        entry = CostLedger.objects.get(persona=_p())
        assert entry.cost_bucket == E.CostBucket.MEDIA_GENERATION
        assert entry.unit == "images" and entry.amount_eur_cents == r.cost_eur_cents == 4


class TestPhoto:
    def _portrait(self):
        with bind(actor_id="user:slobodan"):
            return generator.make_portrait(_p(), actor="user:slobodan", now=NOW)

    def test_photo_edits_the_reference(self, slike):
        self._portrait()
        with bind(actor_id="user:slobodan"):
            r = generator.make_photo(_p(), "u magacinu pored paleta",
                                     actor="user:slobodan", now=NOW)
        assert slike[-1]["path"] == "/edits" and slike[-1]["has_image"] is True
        assert "nepromenjenog lica" in r.prompt and "magacinu" in r.prompt
        assert r.asset.kind == E.AssetKind.PHOTO
        assert generator.gallery_of(_p()) == [r.asset]

    def test_photo_needs_portrait_first(self, slike):
        with bind(actor_id="user:slobodan"), pytest.raises(generator.ImageError) as e:
            generator.make_photo(_p(), "u kancelariji", actor="user:slobodan", now=NOW)
        assert e.value.code == "NO_REFERENCE" and not slike

    def test_empty_scene_refused(self, slike):
        self._portrait()
        with bind(actor_id="user:slobodan"), pytest.raises(generator.ImageError) as e:
            generator.make_photo(_p(), "   ", actor="user:slobodan", now=NOW)
        assert e.value.code == "VALIDATION_ERROR"

    @pytest.mark.parametrize("scene", [
        "sa logotipom firme na majici",
        "drži ličnu kartu u ruci",
    ])
    def test_forbidden_scene_never_reaches_provider(self, slike, scene):
        self._portrait()
        before = len(slike)
        with bind(actor_id="user:slobodan"), pytest.raises(generator.ImageError) as e:
            generator.make_photo(_p(), scene, actor="user:slobodan", now=NOW)
        assert e.value.code == "HARD_PROHIBITION" and len(slike) == before

    def test_daily_cap(self, slike, settings):
        settings.IMAGES_PER_DAY = 2
        self._portrait()
        with bind(actor_id="user:slobodan"):
            generator.make_photo(_p(), "u kancelariji", actor="user:slobodan", now=NOW)
            with pytest.raises(generator.ImageError) as e:
                generator.make_photo(_p(), "na sajmu", actor="user:slobodan", now=NOW)
        assert e.value.code == "THROTTLED"
