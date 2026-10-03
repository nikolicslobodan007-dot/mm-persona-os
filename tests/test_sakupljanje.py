"""ADR-0059 — agent sme da sakuplja znanje, ali ne sme da ga uzme.

Ovde se brane tri tvrdnje, i sve tri u bazi ili u katalogu, ne u servisu:

  - **izvor sa javnog weba bez adrese ne ulazi.** Zapis bez adrese nije izvor
    nego tvrdnja, a posle godinu dana se ne razlikuje od tačnog;
  - **kutija `SLOBODNA` mora da imenuje licencu.** Tvrdnja o dozvoli bez imena
    licence je pogađanje;
  - **podrazumevana kutija je `NEPOZNATA`**, i to znači „nema dozvole", ne
    „slobodno je" (ADR-0059 §2, ADR-0032 §4).

Katalog se proverava zato što je `knowledge.collect` **L1, ne L0**: čitanje ne
ostavlja trag, upis ostavlja.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.memory.models import KnowledgeSource
from apps.policy import config as policy_config
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

#: `requires_db` je SAMO preskakanje kad baze nema — pristup bazi i dalje traži
#: fixture `db`. Bez nje test puca u `connection.cursor()`, a ne kaže zašto.


class TestKatalog:
    def test_knowledge_collect_postoji_i_trazi_l1(self):
        spec = policy_config.capability("knowledge.collect")
        assert spec is not None, "ADR-0059 §1 — capability mora da postoji"
        assert spec["min_trust_level"] == "L1"

    def test_trazi_izvor_i_licencu(self):
        uslovi = policy_config.capability("knowledge.collect")["required_constraints"]
        assert uslovi["source_url_required"] is True
        assert uslovi["license_required"] is True

    def test_akcija_trazi_i_citanje_i_upis(self):
        """Upis bez prava čitanja nema smisla; čitanje bez upisa je `browser.page.read`."""
        traze = policy_config.action_types()["knowledge.collect"]
        assert set(traze) == {"web.read_public", "knowledge.collect"}

    def test_upis_je_interna_akcija(self):
        """Upis ide u NAŠU memoriju — publika je `internal`, novina se ne računa."""
        assert "knowledge.collect" in E.INTERNAL_ACTION_TYPES

    def test_rizik_nije_podrazumevanih_50(self):
        """Akcija koje nema u tabeli dobija 50 i traži odobrenje bez razloga."""
        assert policy_config.weights()["action_base_risk"]["knowledge.collect"] == 5


class TestLicenca:
    def _izvor(self, **kw):
        podaci = dict(source_kind=E.SourceKind.PUBLIC_WEB_SOURCE.value,
                      title="Proba", uri="https://example.com/x", trust_score="0.5")
        return KnowledgeSource.objects.create(**(podaci | kw))

    def test_podrazumevana_kutija_je_nepoznata(self, db):
        assert self._izvor().license_box == E.LicenseBox.NEPOZNATA.value

    def test_web_izvor_bez_adrese_ne_ulazi(self, db):
        with pytest.raises(IntegrityError), transaction.atomic():
            self._izvor(uri="")

    def test_slobodna_bez_imena_licence_ne_ulazi(self, db):
        with pytest.raises(IntegrityError), transaction.atomic():
            self._izvor(license_box=E.LicenseBox.SLOBODNA.value)

    def test_slobodna_sa_imenom_licence_ulazi(self, db):
        izvor = self._izvor(license_box=E.LicenseBox.SLOBODNA.value, license_note="MIT")
        assert izvor.license_note == "MIT"

    def test_zarazna_i_zabranjena_ne_traze_ime(self, db):
        """Odbijanje ne mora da se obrazlaže imenom — dozvola mora."""
        for kutija in (E.LicenseBox.ZARAZNA, E.LicenseBox.ZABRANJENA):
            assert self._izvor(license_box=kutija.value).pk

    def test_samo_slobodna_sme_u_klijentski_projekat(self):
        assert E.LICENSE_BOXES_USABLE == frozenset({E.LicenseBox.SLOBODNA})

    def test_bez_licence_nije_slobodno(self):
        """ADR-0059 §2 — `NEPOZNATA` nije u kutijama koje se smeju koristiti."""
        assert E.LicenseBox.NEPOZNATA not in E.LICENSE_BOXES_USABLE
