"""Testovi semantičkog rangiranja veština (ADR-0120).

Prave model NE pozivamo — fastembed/ONNX nije u gejt-slici i HuggingFace je
zatvoren u pesku. Zato se `embeddings.embed_semanticki` lažira determinističkim
vektorom: tako se meri UGOVOR (embedovanje pri uvozu, text_hash preskok,
kosinusni poredak, leksički fallback, zadržavanje neembedovane veštine), a ne
sam model. Dimenzija vektora je `settings.VESTINA_EMBEDDING_DIM`.
"""

from __future__ import annotations

import pytest
from django.conf import settings

from apps.memory import context, embeddings, vestine
from apps.memory.models import KnowledgeEmbedding, KnowledgeFact
from apps.memory.vestine import PREDIKAT, Vestina, uvezi
from common import enums as E
from tests.conftest import requires_db

DIM = settings.VESTINA_EMBEDDING_DIM
#: reč-marker → indeks koji lažni model „upali"; isti marker u upitu i u
#: veštini daju isti vektor, pa im je kosinusna razdaljina 0.
MARKERI = {"alfa": 0, "beta": 1, "gama": 2}


def _laz_vektor(text: str, *, model=None):
    v = [0.0] * DIM
    low = text.lower()
    pogodak = False
    for marker, i in MARKERI.items():
        if marker in low:
            v[i] = 1.0
            pogodak = True
    if not pogodak:
        v[DIM - 1] = 1.0
    return v


def _v(ime, marker):
    return Vestina(ime=ime, koraci=[f"uradi {marker}"],
                   napomene=f"koristi kad je zadatak {marker}", pouzdanost=0.9)


def _uvezi(vestine_, naslov="Semantika izvor"):
    return uvezi(naslov_izvora=naslov, uri="https://example.com/sem",
                 license_box=E.LicenseBox.SLOBODNA, license_note="MIT",
                 vestine=vestine_, actor="user:qa")


@requires_db
@pytest.mark.django_db
def test_uvoz_embeduje_vestine(db, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    _uvezi([_v("vestina-alfa", "alfa"), _v("vestina-beta", "beta")])
    assert KnowledgeEmbedding.objects.count() == 2
    mk = embeddings.vestina_model_key()
    assert all(e.model_key == mk and e.dimensions == DIM
               for e in KnowledgeEmbedding.objects.all())


@requires_db
@pytest.mark.django_db
def test_uvoz_bez_modela_ne_pada(db, monkeypatch):
    def pukni(text, *, model=None):
        raise RuntimeError("model nedostupan (offline)")

    monkeypatch.setattr(embeddings, "embed_semanticki", pukni)
    broj = _uvezi([_v("vestina-alfa", "alfa")])
    assert broj["upisano"] == 1
    assert KnowledgeFact.objects.filter(predicate=PREDIKAT).count() == 1
    assert KnowledgeEmbedding.objects.count() == 0


@requires_db
@pytest.mark.django_db
def test_text_hash_preskace_ponovno_racunanje(db, monkeypatch):
    brojac = {"n": 0}

    def broji(text, *, model=None):
        brojac["n"] += 1
        return _laz_vektor(text)

    monkeypatch.setattr(embeddings, "embed_semanticki", broji)
    _uvezi([_v("vestina-alfa", "alfa")])
    assert brojac["n"] == 1
    facts = list(KnowledgeFact.objects.filter(predicate=PREDIKAT))
    drugi = vestine.embeduj(facts)
    assert brojac["n"] == 1  # nije ponovo računao
    assert drugi == {"upisano": 0, "preskoceno": 1}


@requires_db
@pytest.mark.django_db
def test_semanticki_poredak_dize_pravu_vestinu(db, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    _uvezi([_v("vestina-alfa", "alfa"), _v("vestina-beta", "beta"),
            _v("vestina-gama", "gama")])
    poredak = context._rangiraj_vestine(None, "treba mi zadatak beta", "")
    assert poredak[0].subject == "vestina-beta"
    assert {f.subject for f in poredak} == {"vestina-alfa", "vestina-beta", "vestina-gama"}


@requires_db
@pytest.mark.django_db
def test_bez_vektora_pada_na_leksicko(db, monkeypatch):
    def pukni(text, *, model=None):
        raise RuntimeError("offline")

    monkeypatch.setattr(embeddings, "embed_semanticki", pukni)
    _uvezi([_v("vestina-alfa", "alfa"), _v("vestina-beta", "beta")])
    assert KnowledgeEmbedding.objects.count() == 0
    # model sad „radi" za upit, ali baza nema vektore → _semanticki_rang vrati
    # None, pa rangiranje padne na leksičko i svejedno vrati sve veštine.
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    poredak = context._rangiraj_vestine(None, "zadatak alfa", "")
    assert context._semanticki_rang("zadatak alfa", poredak) is None
    assert {f.subject for f in poredak} == {"vestina-alfa", "vestina-beta"}


@requires_db
@pytest.mark.django_db
def test_neembedovana_vestina_ostaje_u_poretku(db, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_semanticki", _laz_vektor)
    _uvezi([_v("vestina-alfa", "alfa"), _v("vestina-beta", "beta")])
    # treća veština bez vektora (kao sveže uvezena pre dopune)
    izvor = KnowledgeFact.objects.filter(predicate=PREDIKAT).first().source
    nova = KnowledgeFact.objects.create(
        source=izvor, persona=None, subject="vestina-nova", predicate=PREDIKAT,
        provenance=E.Provenance.USER_PROVIDED.value, confidence=0.9,
        object_json={"koraci": ["x"], "napomene": "bez markera"})
    poredak = context._rangiraj_vestine(None, "zadatak alfa", "")
    subjekti = [f.subject for f in poredak]
    assert "vestina-nova" in subjekti
    assert subjekti[-1] == "vestina-nova"  # neembedovana ide na kraj
    assert subjekti[0] == "vestina-alfa"
    assert nova.id in {f.id for f in poredak}
