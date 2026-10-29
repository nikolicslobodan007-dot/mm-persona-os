"""Testovi uvoza dolazne poruke u sloj znanja (ADR-0031 §4, sloj 2).

`ugradi_poruku` čita samo `subject`/`body_text`/`provider_message_id`/`from_addr`
sa poruke (ne query-ja `MailMessage`), pa se upis testira sa lažnom porukom
(`SimpleNamespace`) — bez teškog fixtura (persona + nalog). Parser je čista funkcija.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.libri import uvoz_mail
from apps.libri.uvoz import UvozError
from common import enums as E
from tests.conftest import requires_db


def _poruka(subject="Ponuda furnira", body=None, mid="<abc@firma.rs>",
            frm="prodaja@firma.rs"):
    if body is None:
        body = ("Poštovani,\n\nŠaljemo ponudu za furnir.\n\n"
                "Furnir je tanak list drveta koji se lepi preko osnove.\n\nPozdrav.")
    return SimpleNamespace(subject=subject, body_text=body,
                           provider_message_id=mid, from_addr=frm)


# ---- parser (čista funkcija) ----

def test_naslov_i_blokovi_naslov_i_pasusi():
    blokovi, lang, script = uvoz_mail.naslov_i_blokovi(
        "Ponuda furnira",
        "Poštovani,\n\nŠaljemo ponudu za furnir.\n\nFurnir je tanak list drveta.")
    tekstovi = [b["text"] for b in blokovi]
    assert "Ponuda furnira" in tekstovi
    glave = [b for b in blokovi if b["block_type"] == "heading"]
    assert glave and glave[0]["text"] == "Ponuda furnira"
    pasusi = [b for b in blokovi if b["block_type"] == "paragraph"]
    assert any("Šaljemo ponudu" in t for t in tekstovi)
    assert pasusi[0]["heading_path"] == ["Ponuda furnira"]
    assert pasusi[0]["source_page"] is None          # mejl nema strane


def test_naslov_i_blokovi_prazno_nema_blokova():
    blokovi, _lang, _script = uvoz_mail.naslov_i_blokovi("", "")
    assert blokovi == []


# ---- upis (lažna poruka, bez MailMessage fixtura) ----

@requires_db
@pytest.mark.django_db
def test_ugradi_poruku_pravi_first_party_izvor(db):
    dok = uvoz_mail.ugradi_poruku(_poruka(), licenca="NEPOZNATA")
    assert dok.document_id.startswith("mail_")
    assert dok.source.source_kind == E.SourceKind.FIRST_PARTY_USER_INPUT.value
    assert dok.source.trust_score == uvoz_mail.TRUST_MAIL
    assert dok.source.uri.startswith("mailmsg:")
    assert dok.blocks.count() >= 2                   # naslov + bar jedan pasus
    assert dok.title == "Ponuda furnira"


@requires_db
@pytest.mark.django_db
def test_ugradi_poruku_dedup(db):
    uvoz_mail.ugradi_poruku(_poruka(mid="<a@x>"), licenca="NEPOZNATA")
    with pytest.raises(UvozError, match="već uvezen"):
        uvoz_mail.ugradi_poruku(_poruka(mid="<b@x>"), licenca="NEPOZNATA")  # isti sadržaj


@requires_db
@pytest.mark.django_db
def test_ugradi_poruku_losa_licenca(db):
    with pytest.raises(UvozError, match="licenca"):
        uvoz_mail.ugradi_poruku(_poruka(), licenca="IZMISLJENA")


@requires_db
@pytest.mark.django_db
def test_ugradi_poruku_prazna_pada(db):
    with pytest.raises(UvozError, match="iskoristivog teksta"):
        uvoz_mail.ugradi_poruku(_poruka(subject="", body="   \n\n  "), licenca="NEPOZNATA")
