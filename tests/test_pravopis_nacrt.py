"""ADR-0056 — nalazi Rečnika stoje uz nacrt, a ne u komandnoj liniji.

ADR-0055 je ostavio proveru koju je mogao da pozove samo čovek preko `manage.py`.
Urednik ne radi tako: on otvori nacrt. Ovde se proverava da nalaz stigne do njega,
i — jednako važno — da se prazan nalaz ne pravi da je provera prošla kad je nije
ni bilo.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import Group, User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.content import recnik, service
from apps.content.models import ContentItem
from common import enums as E
from tests.conftest import requires_db

ODREDNICE = [
    {"odrednica": "avlija", "odrednica_cir": "авлија",
     "tekst": "avlija (ne havlija)", "tekst_cir": "авлија (не хавлија)",
     "tacke": ["157e"], "strana_pdf": 334, "ne": ["havlija"]},
]


@pytest.fixture
def recnik_uvezen(db, tmp_path):
    p = tmp_path / "recnik.jsonl"
    p.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in ODREDNICE),
                 encoding="utf-8")
    recnik.uvezi(putanja=p)
    return p


def _nacrt(persona, tekst):
    from api.context import bind

    with bind(actor_id="user:slobodan"):
        return service.draft(persona=persona, topic="Tema", body=tekst)


@pytest.fixture
def klijent(db, mila):
    u = User.objects.create_user("urednik1", password="x")
    u.groups.add(Group.objects.get(name=E.Role.OPERATOR.value))
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}",
                  HTTP_X_ACTOR_ID="user:urednik1", HTTP_X_REQUEST_ID="test-0056-0001")
    return c


@requires_db
class TestNalazUzNacrt:
    def test_nacrt_nosi_nalaz(self, db, mila, recnik_uvezen):
        item = _nacrt(mila, "Ušao je u havliju i seo.")
        assert item.pravopis["provereno"] is True
        nalaz = item.pravopis["nalazi"][0]
        assert nalaz["oblik"] == "havliju"
        assert nalaz["odrednica"] == "avlija"
        assert nalaz["tacke"] == ["157e"]

    def test_ispravan_tekst_nosi_prazan_spisak(self, db, mila, recnik_uvezen):
        item = _nacrt(mila, "Ušao je u avliju i seo.")
        assert item.pravopis == {"provereno": True, "nalazi": []}

    def test_bez_recnika_se_ne_tvrdi_da_je_provereno(self, db, mila):
        """Prazan nalaz i neuvezen rečnik izgledaju isto — i ne smeju."""
        item = _nacrt(mila, "Ušao je u havliju i seo.")
        assert item.pravopis == {"provereno": False, "nalazi": []}

    def test_nalaz_ne_obara_nacrt(self, db, mila, recnik_uvezen):
        """Spisak je izveden obrascem i ume da pogreši — odlučuje urednik."""
        item = _nacrt(mila, "Ušao je u havliju i seo.")
        assert item.status == E.ContentStatus.DRAFT.value
        assert item.status_reason == ""

    def test_nalaz_stize_do_urednika_kroz_api(self, db, mila, recnik_uvezen, klijent):
        item = _nacrt(mila, "Ušao je u havliju i seo.")
        r = klijent.get(f"/api/v1/content/items/{item.id}")
        assert r.status_code == 200
        telo = r.json()["data"]
        assert telo["pravopis"]["nalazi"][0]["oblik"] == "havliju"

    def test_i_ljudski_tekst_se_proverava(self, db, mila, recnik_uvezen):
        """Urednik gleda svaki nacrt; poreklo teksta ne menja šta se proverava."""
        item = _nacrt(mila, "Ušao je u havliju.")
        assert item.provenance == E.Provenance.USER_PROVIDED.value
        assert item.pravopis["nalazi"]

    def test_zatecen_nacrt_nema_nalaz(self, db, mila):
        """Migracija ne izmišlja nalaze za ono što je napisano pre nje."""
        stari = ContentItem.objects.create(
            persona=mila, format=E.ContentFormat.POST.value, title="Staro",
            body="Ušao je u havliju.", language="sr-Latn-RS",
            status=E.ContentStatus.DRAFT.value,
            provenance=E.Provenance.USER_PROVIDED.value)
        assert stari.pravopis == {}


@requires_db
class TestKonzola:
    """Urednik ne otvara API nego stranicu Sadržaj — nalaz mora biti tamo."""

    @pytest.fixture
    def sef(self, db, mila):
        import io

        from django.core.management import call_command

        u = User.objects.create_user("sef56", password="Tajna-lozinka-1")
        u.groups.add(Group.objects.get(name=E.Role.SYSTEM_ADMIN.value))
        u.user_permissions.add(
            *Group.objects.get(name=E.Role.OPERATOR.value).permissions.all())
        call_command("console_totp", user="sef56", stdout=io.StringIO())
        return u

    def _konzola(self, korisnik):
        from django.test import Client

        from tests.test_console import _login

        return _login(Client(), korisnik)

    def test_nalaz_se_vidi_na_stranici(self, db, mila, recnik_uvezen, sef):
        _nacrt(mila, "Ušao je u havliju i seo.")
        telo = self._konzola(sef).get("/console/content").content.decode()
        assert "havliju" in telo
        assert "avlija (ne havlija)" in telo
        assert "t. 157e" in telo

    def test_neuvezen_recnik_se_kaze_a_ne_precuti(self, db, mila, sef):
        _nacrt(mila, "Ušao je u havliju i seo.")
        telo = self._konzola(sef).get("/console/content").content.decode()
        assert "nije provereno" in telo

    def test_zatecen_nacrt_ne_tvrdi_nista(self, db, mila, sef):
        """Nacrt napisan pre ADR-0056 nema šta da kaže — ni da jeste ni da nije."""
        ContentItem.objects.create(
            persona=mila, format=E.ContentFormat.POST.value, title="Staro",
            body="Ušao je u havliju.", language="sr-Latn-RS",
            status=E.ContentStatus.DRAFT.value,
            provenance=E.Provenance.USER_PROVIDED.value)
        telo = self._konzola(sef).get("/console/content").content.decode()
        assert "Pravopis" not in telo
