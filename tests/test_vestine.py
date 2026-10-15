"""Testovi za uvoz veština (ADR-0074) i za spisak veština (ADR-0084).

Komanda `vestina` i modul `apps/memory/vestine.py` su u pogonu od 04.10. i
do sada ih je čuvao jedino CHECK u bazi. Ovi testovi proveravaju ugovor koji
kod obećava, pre nego što nešto drugo probije ogradu.
"""

from __future__ import annotations

import io
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.memory.models import KnowledgeFact, KnowledgeSource
from apps.memory.vestine import Vestina, uvezi
from apps.observability.models import AuditEvent
from common import enums as E
from tests.conftest import requires_db


def _vestina(ime="oparivanje testa", pouzdanost=0.8):
    return Vestina(
        ime=ime,
        koraci=["zagrej vodu na 27C", "umesi testo", "ostavi da nadođe"],
        napomene="radi bolje leti",
        pouzdanost=pouzdanost,
    )


@requires_db
@pytest.mark.django_db
def test_uvoz_je_idempotentan(db):
    prvi = uvezi(
        naslov_izvora="Kuvarska veština A",
        uri="https://example.com/a",
        license_box=E.LicenseBox.SLOBODNA,
        license_note="MIT",
        vestine=[_vestina()],
        actor="user:qa",
    )
    drugi = uvezi(
        naslov_izvora="Kuvarska veština A",
        uri="https://example.com/a",
        license_box=E.LicenseBox.SLOBODNA,
        license_note="MIT",
        vestine=[_vestina()],
        actor="user:qa",
    )

    assert prvi["upisano"] == 1
    assert drugi["upisano"] == 1
    assert drugi["obrisano"] == 1

    izvor = KnowledgeSource.objects.get(title="Kuvarska veština A")
    broj_cinjenica = KnowledgeFact.objects.filter(
        source=izvor, predicate="vestina.postupak"
    ).count()
    assert broj_cinjenica == 1


@requires_db
@pytest.mark.django_db
def test_pouzdanost_van_opsega_die_pre_transakcije(db):
    with pytest.raises(ValueError):
        uvezi(
            naslov_izvora="Izvor van opsega",
            uri="https://example.com/b",
            license_box=E.LicenseBox.SLOBODNA,
            license_note="MIT",
            vestine=[_vestina(pouzdanost=1.5)],
            actor="user:qa",
        )

    assert not KnowledgeSource.objects.filter(title="Izvor van opsega").exists()
    assert not KnowledgeFact.objects.filter(predicate="vestina.postupak").exists()


@requires_db
@pytest.mark.django_db
def test_slobodna_kutija_bez_naziva_licence_staje_u_komandi(db, tmp_path):
    datoteka = tmp_path / "vestine.json"
    datoteka.write_text(
        json.dumps(
            [
                {
                    "ime": "test veština",
                    "koraci": ["korak 1"],
                    "napomene": "",
                    "pouzdanost": 0.5,
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError):
        call_command(
            "vestina",
            "--izvor=Bez licence",
            "--uri=https://example.com/c",
            "--licenca=SLOBODNA",
            f"--datoteka={datoteka}",
            "--actor=user:qa",
            stdout=io.StringIO(),
        )

    assert not KnowledgeSource.objects.filter(title="Bez licence").exists()


@requires_db
@pytest.mark.django_db
def test_actor_koji_ne_pocinje_sa_user_staje_u_komandi(db, tmp_path):
    datoteka = tmp_path / "vestine.json"
    datoteka.write_text(
        json.dumps(
            [
                {
                    "ime": "test veština",
                    "koraci": ["korak 1"],
                    "napomene": "",
                    "pouzdanost": 0.5,
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError):
        call_command(
            "vestina",
            "--izvor=Los actor",
            "--uri=https://example.com/d",
            "--licenca=ZABRANJENA",
            f"--datoteka={datoteka}",
            "--actor=agent:qa",
            stdout=io.StringIO(),
        )

    assert not KnowledgeSource.objects.filter(title="Los actor").exists()


@requires_db
@pytest.mark.django_db
def test_knowledge_source_dobija_tacne_vrednosti(db):
    uvezi(
        naslov_izvora="Izvor tacnih vrednosti",
        uri="https://example.com/tacno",
        license_box=E.LicenseBox.ZARAZNA,
        license_note="GPL-3.0",
        vestine=[_vestina()],
        actor="user:qa",
    )

    izvor = KnowledgeSource.objects.get(title="Izvor tacnih vrednosti")
    assert izvor.source_kind == E.SourceKind.FIRST_PARTY_USER_INPUT.value
    assert izvor.uri == "https://example.com/tacno"
    assert izvor.license_box == E.LicenseBox.ZARAZNA.value
    assert izvor.license_note == "GPL-3.0"


@requires_db
@pytest.mark.django_db
def test_object_json_nema_doslovan_prepis_izvora(db):
    uvezi(
        naslov_izvora="Izvor bez prepisa",
        uri="https://example.com/prepis",
        license_box=E.LicenseBox.NEPOZNATA,
        license_note="",
        vestine=[_vestina()],
        actor="user:qa",
    )

    izvor = KnowledgeSource.objects.get(title="Izvor bez prepisa")
    cinjenica = KnowledgeFact.objects.get(source=izvor, predicate="vestina.postupak")

    assert set(cinjenica.object_json.keys()) == {"koraci", "napomene"}
    for zabranjen_kljuc in ("izvorni_tekst", "raw", "original", "doslovan_tekst", "source_text"):
        assert zabranjen_kljuc not in cinjenica.object_json


@requires_db
@pytest.mark.django_db
def test_spisak_ispisuje_upisanu_vestinu(db):
    uvezi(
        naslov_izvora="Spisak izvor A",
        uri="https://example.com/spisak-a",
        license_box=E.LicenseBox.SLOBODNA,
        license_note="MIT",
        vestine=[_vestina(ime="veština za spisak")],
        actor="user:qa",
    )

    stdout = io.StringIO()
    call_command("vestina", "--spisak", stdout=stdout)
    izlaz = stdout.getvalue()

    assert "veština za spisak" in izlaz
    assert "Spisak izvor A" in izlaz
    assert E.LicenseBox.SLOBODNA.value in izlaz


@requires_db
@pytest.mark.django_db
def test_spisak_prazna_baza_daje_recenicu(db):
    stdout = io.StringIO()
    call_command("vestina", "--spisak", stdout=stdout)
    izlaz = stdout.getvalue().strip()

    assert izlaz == "Nema upisanih veština u bazi znanja."
    assert izlaz != ""


@requires_db
@pytest.mark.django_db
def test_spisak_filtrira_po_izvoru(db):
    uvezi(
        naslov_izvora="Izvor jedan filter",
        uri="https://example.com/filter-1",
        license_box=E.LicenseBox.NEPOZNATA,
        license_note="",
        vestine=[_vestina(ime="vestina iz izvora jedan")],
        actor="user:qa",
    )
    uvezi(
        naslov_izvora="Izvor dva filter",
        uri="https://example.com/filter-2",
        license_box=E.LicenseBox.NEPOZNATA,
        license_note="",
        vestine=[_vestina(ime="vestina iz izvora dva")],
        actor="user:qa",
    )

    stdout = io.StringIO()
    call_command("vestina", "--spisak", "--izvor=jedan", stdout=stdout)
    izlaz = stdout.getvalue()

    assert "vestina iz izvora jedan" in izlaz
    assert "vestina iz izvora dva" not in izlaz


@requires_db
@pytest.mark.django_db
def test_komanda_upisuje_coveka_u_audit_trag(db, tmp_path):
    """ADR-0074: audit mora da vidi --actor, ne podrazumevani service:system."""
    datoteka = tmp_path / "vestine.json"
    datoteka.write_text(
        json.dumps(
            [
                {
                    "ime": "veština za audit",
                    "koraci": ["korak 1"],
                    "napomene": "",
                    "pouzdanost": 0.5,
                }
            ]
        ),
        encoding="utf-8",
    )

    call_command(
        "vestina",
        "--izvor=Audit izvor",
        "--uri=https://example.com/audit",
        "--licenca=NEPOZNATA",
        f"--datoteka={datoteka}",
        "--actor=user:audit-qa",
        stdout=io.StringIO(),
    )

    dogadjaj = AuditEvent.objects.get(event_key="memory.vestina.loaded")
    assert dogadjaj.actor_ref == "user:audit-qa"
    assert dogadjaj.actor_ref != "service:system"
