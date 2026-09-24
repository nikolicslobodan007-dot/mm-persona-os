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


class TestUpload:
    """Dopuna ADR-0018 (24.09.) — slike napravljene ručno, bez API-ja."""

    JPEG = b"\xff\xd8\xff\xe0" + b"rucna slika"

    def test_upload_works_without_generator(self, slike, settings):
        settings.IMAGE_ENABLED = False
        with bind(actor_id="user:slobodan"):
            r = generator.import_image(_p(), PNG, actor="user:slobodan",
                                       as_portrait=True, now=NOW)
        assert not slike                      # provajder nije pozvan
        assert r.cost_eur_cents == 0 and not CostLedger.objects.exists()
        assert r.asset.kind == E.AssetKind.FACE_REFERENCE
        assert r.asset.generation_model == generator.MANUAL_MODEL
        assert "AI" in r.asset.rights_note and r.asset.origin == "generated"
        assert generator.reference_of(_p()).pk == r.asset.pk

    def test_uploaded_photo_goes_to_gallery(self, slike):
        with bind(actor_id="user:slobodan"):
            generator.import_image(_p(), PNG, actor="user:slobodan", as_portrait=True,
                                   now=NOW)
            r = generator.import_image(_p(), self.JPEG, actor="user:slobodan",
                                       label="na sajmu", now=NOW)
        assert r.asset.kind == E.AssetKind.PHOTO
        assert r.asset.mime_type == "image/jpeg"
        assert generator.gallery_of(_p()) == [r.asset]

    def test_same_file_is_not_stored_twice(self, slike):
        with bind(actor_id="user:slobodan"):
            a = generator.import_image(_p(), PNG, actor="user:slobodan", now=NOW)
            b = generator.import_image(_p(), PNG, actor="user:slobodan", now=NOW)
        assert a.asset.pk == b.asset.pk and MediaAsset.objects.count() == 1

    @pytest.mark.parametrize("data,why", [
        (b"", "prazan"),
        (b"%PDF-1.7 nije slika", "nije slika"),
    ])
    def test_bad_file_refused(self, slike, data, why):
        with bind(actor_id="user:slobodan"), pytest.raises(generator.ImageError) as e:
            generator.import_image(_p(), data, actor="user:slobodan", now=NOW)
        assert e.value.code == "VALIDATION_ERROR", why

    def test_too_big_refused(self, slike):
        big = PNG + b"x" * (generator.MAX_UPLOAD_BYTES + 1)
        with bind(actor_id="user:slobodan"), pytest.raises(generator.ImageError) as e:
            generator.import_image(_p(), big, actor="user:slobodan", now=NOW)
        assert e.value.code == "VALIDATION_ERROR"

    def test_upload_does_not_spend_daily_cap(self, slike, settings):
        settings.IMAGES_PER_DAY = 1
        with bind(actor_id="user:slobodan"):
            generator.import_image(_p(), PNG, actor="user:slobodan", now=NOW)
            generator.import_image(_p(), self.JPEG, actor="user:slobodan", now=NOW)
        assert MediaAsset.objects.count() == 2


class TestUklanjanje:
    """Dopuna ADR-0018 (24.09.) — slika mora da može i da se skloni.

    Na koga lice liči ne vidi nijedna provera, nego čovek; put unazad je zato
    deo postupka, a ne ispravka.
    """

    JPEG = b"\xff\xd8\xff\xe0" + b"scena"

    @pytest.fixture
    def obrisano(self, monkeypatch):
        kljucevi: list[str] = []
        monkeypatch.setattr(storage, "drop", kljucevi.append)
        return kljucevi

    def test_gallery_image_disappears_everywhere(self, slike, obrisano):
        from apps.visuals.models import AssetCollectionItem

        with bind(actor_id="user:slobodan"):
            generator.import_image(_p(), PNG, actor="user:slobodan", as_portrait=True,
                                   now=NOW)
            a = generator.import_image(_p(), self.JPEG, actor="user:slobodan",
                                       label="na sajmu", now=NOW).asset
            kljuc, oznaka = a.storage_key, a.public_id
            assert generator.remove_asset(_p(), a, actor="user:slobodan") == oznaka
        assert not MediaAsset.objects.filter(public_id=oznaka).exists()
        assert not AssetCollectionItem.objects.exists()
        assert generator.gallery_of(_p()) == []
        assert obrisano == [kljuc]                     # i fajl je sklonjen

    def test_removing_portrait_drops_the_anchor(self, slike, obrisano):
        with bind(actor_id="user:slobodan"):
            a = generator.import_image(_p(), PNG, actor="user:slobodan",
                                       as_portrait=True, now=NOW).asset
            generator.remove_asset(_p(), a, actor="user:slobodan")
        assert generator.reference_of(_p()) is None
        vp = VisualProfile.objects.get(persona=_p())
        assert vp.consistency_version == 3                # 1 pri upisu, +1, +1
        with bind(actor_id="user:slobodan"), pytest.raises(generator.ImageError) as e:
            generator.make_photo(_p(), "u magacinu", actor="user:slobodan", now=NOW)
        assert e.value.code == "NO_REFERENCE"

    def test_number_of_the_next_image_is_free(self, slike, obrisano):
        """Posle uklanjanja iz sredine broj se ne sme vratiti na zauzet."""
        with bind(actor_id="user:slobodan"):
            generator.import_image(_p(), PNG, actor="user:slobodan", now=NOW)
            druga = generator.import_image(_p(), self.JPEG, actor="user:slobodan",
                                           now=NOW).asset
            generator.import_image(_p(), PNG + b"treca", actor="user:slobodan", now=NOW)
            assert druga.public_id.endswith("-0002")
            generator.remove_asset(_p(), druga, actor="user:slobodan")
            cetvrta = generator.import_image(_p(), PNG + b"cetvrta",
                                             actor="user:slobodan", now=NOW).asset
        assert cetvrta.public_id.endswith("-0004")

    def test_other_personas_image_is_refused(self, slike, obrisano):
        from apps.personas.models import Position

        with bind(actor_id="user:slobodan"):
            from apps.personas import hiring

            tudja = hiring.hire(name="Ana Perić", position=Position.objects.get(
                code="POD-SR"), actor="user:slobodan")
            a = generator.import_image(_p(), PNG, actor="user:slobodan", now=NOW).asset
            with pytest.raises(generator.ImageError) as e:
                generator.remove_asset(tudja, a, actor="user:slobodan")
        assert e.value.code == "VALIDATION_ERROR"
        assert MediaAsset.objects.filter(pk=a.pk).exists()
        assert not obrisano

    def test_removal_is_written_in_audit(self, slike, obrisano):
        from apps.observability.models import AuditEvent

        with bind(actor_id="user:slobodan"):
            a = generator.import_image(_p(), PNG, actor="user:slobodan",
                                       as_portrait=True, now=NOW).asset
            generator.remove_asset(_p(), a, actor="user:slobodan")
        e = AuditEvent.objects.filter(event_key="visual.asset.removed").first()
        assert e is not None and e.payload["details"]["was_portrait"] is True
