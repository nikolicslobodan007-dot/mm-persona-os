"""Libri sloj 2 — uvoz PDF-a (ADR-0031). Meri grind + uvoz + dedup u bazi."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.libri.grind import grind
from apps.libri.models import LibriDocument
from apps.libri.uvoz import UvozError, uvezi
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

PROBA = str(Path(__file__).parent / "fixtures" / "libri" / "proba.pdf")


class TestGrind:
    def test_grind_izvlaci_blokove(self):
        meta, blokovi = grind(PROBA)
        assert meta["pages"] == 2
        assert meta["document_id"].startswith("doc_")
        assert meta["language"] == "sr-Latn"
        headinzi = [b for b in blokovi if b["block_type"] == "heading"]
        assert len(headinzi) == 2
        assert all(b["source_page"] in (1, 2) for b in blokovi)
        assert all(0 <= b["extraction_confidence"] <= 1 for b in blokovi)
        assert all(b["text"].strip() not in ("1", "2") for b in blokovi)


class TestUvoz:
    def test_uvoz_pravi_izvor_dokument_blokove(self, db):
        dok = uvezi(PROBA, naslov="Proba stolarije",
                    licenca="SLOBODNA", naziv_licence="Sopstveni rad")
        assert dok.title == "Proba stolarije"
        assert dok.pages == 2
        assert dok.checksum and len(dok.checksum) == 64
        assert dok.blocks.count() >= 4
        assert dok.source is not None
        assert dok.source.source_kind == E.SourceKind.FIRST_PARTY_USER_INPUT.value
        assert dok.source.license_box == E.LicenseBox.SLOBODNA.value
        assert dok.source.license_note == "Sopstveni rad"

    def test_dedup_po_checksum(self, db):
        uvezi(PROBA, licenca="NEPOZNATA")
        with pytest.raises(UvozError):
            uvezi(PROBA, licenca="NEPOZNATA")
        assert LibriDocument.objects.count() == 1

    def test_slobodna_trazi_naziv_licence(self, db):
        with pytest.raises(UvozError):
            uvezi(PROBA, licenca="SLOBODNA")

    def test_nepostojeci_fajl(self, db):
        with pytest.raises(UvozError):
            uvezi("/nema/ovoga.pdf", licenca="NEPOZNATA")


class TestKomanda:
    def test_komanda_uvezi(self, db):
        out = io.StringIO()
        call_command("libri", "uvezi", "--iz", PROBA,
                     "--licenca", "NEPOZNATA", "--actor", "user:slobodan", stdout=out)
        assert "Uvezeno" in out.getvalue()
        assert LibriDocument.objects.count() == 1

    def test_komanda_actor_mora_user(self, db):
        with pytest.raises(CommandError, match="user:"):
            call_command("libri", "uvezi", "--iz", PROBA,
                         "--licenca", "NEPOZNATA", "--actor", "agent:P-00001")
