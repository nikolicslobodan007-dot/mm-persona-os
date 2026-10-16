"""Testovi za uvoz veština (ADR-0074), komit/putanju (ADR-0077 §3),
osvežavanje pri ponovnom uvozu (ADR-0095) i spisak (ADR-0084).

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
from apps.personas.models import Department
from common import enums as E
from tests.conftest import requires_db


def _vestina(ime="oparivanje testa", pouzdanost=0.8):
    return Vestina(
        ime=ime,
        koraci=["zagrej vodu na 27C", "umesi testo", "ostavi da nadođe"],
        napomene="radi bolje leti",
        pouzdanost=pouzdanost,
    )


def _datoteka(tmp_path, ime="veština iz datoteke"):
    putanja = tmp_path / "vestine.json"
    putanja.write_text(
        json.dumps(
            [
                {
                    "ime": ime,
                    "koraci": ["korak 1"],
                    "napomene": "",
                    "pouzdanost": 0.5,
                }
            ]
        ),
        encoding="utf-8",
    )
    return putanja


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
    datoteka = _datoteka(tmp_path, "test veština")

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
    datoteka = _datoteka(tmp_path, "test veština")

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
    datoteka = _datoteka(tmp_path, "veština za audit")

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


@requires_db
@pytest.mark.django_db
def test_uvoz_sa_commit_i_putanjom_upisuje_vrednosti(db, tmp_path):
    """ADR-0077 §3 — korpus iz repozitorijuma nosi commit i putanju fajla."""
    datoteka = _datoteka(tmp_path, "veština sa commitom")

    call_command(
        "vestina",
        "--izvor=Izvor sa commitom",
        "--uri=https://example.com/repo",
        "--licenca=NEPOZNATA",
        f"--datoteka={datoteka}",
        "--actor=user:qa",
        "--commit=" + "a" * 40,
        "--putanja=korpus/vestine/nasi-adr.json",
        stdout=io.StringIO(),
    )

    izvor = KnowledgeSource.objects.get(title="Izvor sa commitom")
    assert izvor.commit_sha == "a" * 40
    assert izvor.file_path == "korpus/vestine/nasi-adr.json"


@requires_db
@pytest.mark.django_db
def test_izmisljen_sektor_se_odbija(db, tmp_path):
    """ADR-0101 — sektor se proverava po `Department.code`, pre upisa.

    Da greška u imenu sektora ne bude otkrivena tek onda kad agent ostane
    bez veština u paketu, a niko ne zna zašto.
    """
    datoteka = _datoteka(tmp_path, "veština u izmišljenom sektoru")

    with pytest.raises(CommandError, match="Nepoznat sektor"):
        call_command(
            "vestina",
            "--izvor=Izvor sa lošim sektorom",
            "--uri=https://example.com/repo",
            "--licenca=NEPOZNATA",
            f"--datoteka={datoteka}",
            "--actor=user:qa",
            "--sektor=MARKETINK",
            stdout=io.StringIO(),
        )

    assert not KnowledgeSource.objects.filter(title="Izvor sa lošim sektorom").exists()


@requires_db
@pytest.mark.django_db
def test_sektor_se_upisuje_i_osvezava_pri_ponovnom_uvozu(db, tmp_path):
    """ADR-0101 uz ADR-0095 — sektor je šesto polje koje čovek donosi pri
    svakom uvozu, pa se pri ponovnom uvozu osvežava, a ne ostaje staro."""
    Department.objects.create(code="MARKETING", name="Marketing i sadržaj")
    Department.objects.create(code="RAZVOJ", name="Razvoj i održavanje")
    datoteka = _datoteka(tmp_path, "veština sa sektorom")

    def uvezi_sa(sektor):
        call_command(
            "vestina",
            "--izvor=Izvor sa sektorom",
            "--uri=https://example.com/repo",
            "--licenca=NEPOZNATA",
            f"--datoteka={datoteka}",
            "--actor=user:qa",
            f"--sektor={sektor}",
            stdout=io.StringIO(),
        )

    uvezi_sa("razvoj")  # mala slova — komanda ih podiže
    assert KnowledgeSource.objects.get(title="Izvor sa sektorom").sector == "RAZVOJ"

    uvezi_sa("MARKETING")
    assert KnowledgeSource.objects.get(title="Izvor sa sektorom").sector == "MARKETING"


@requires_db
@pytest.mark.django_db
def test_uvoz_bez_sektora_ostavlja_prazno(db, tmp_path):
    """ADR-0101 — bez `--sektor` korpus važi za sve sektore, i to je
    prazan niz znakova, ne None."""
    datoteka = _datoteka(tmp_path, "veština bez sektora")

    call_command(
        "vestina",
        "--izvor=Izvor bez sektora",
        "--uri=https://example.com/dokument",
        "--licenca=NEPOZNATA",
        f"--datoteka={datoteka}",
        "--actor=user:qa",
        stdout=io.StringIO(),
    )

    assert KnowledgeSource.objects.get(title="Izvor bez sektora").sector == ""


@requires_db
@pytest.mark.django_db
def test_uvoz_bez_commit_i_putanje_ostavlja_prazno(db, tmp_path):
    """ADR-0077 §3 — izvor koji nije iz repozitorijuma nosi prazna polja, ne None."""
    datoteka = _datoteka(tmp_path, "veština bez commita")

    call_command(
        "vestina",
        "--izvor=Izvor bez commita",
        "--uri=https://example.com/dokument",
        "--licenca=NEPOZNATA",
        f"--datoteka={datoteka}",
        "--actor=user:qa",
        stdout=io.StringIO(),
    )

    izvor = KnowledgeSource.objects.get(title="Izvor bez commita")
    assert izvor.commit_sha == ""
    assert izvor.file_path == ""
    assert izvor.commit_sha is not None
    assert izvor.file_path is not None


@requires_db
@pytest.mark.django_db
def test_ponovni_uvoz_osvezava_pet_polja(db):
    """ADR-0095 — uri, license_box, license_note, commit_sha i file_path

    se osvežavaju na postojećem redu pri ponovnom uvozu istog naslova.
    """
    uvezi(
        naslov_izvora="Izvor za osvežavanje",
        uri="https://example.com/staro",
        license_box=E.LicenseBox.NEPOZNATA,
        license_note="",
        commit_sha="a" * 40,
        file_path="stara/putanja.json",
        vestine=[_vestina()],
        actor="user:qa",
    )

    uvezi(
        naslov_izvora="Izvor za osvežavanje",
        uri="https://example.com/novo",
        license_box=E.LicenseBox.SLOBODNA,
        license_note="MIT",
        commit_sha="b" * 40,
        file_path="nova/putanja.json",
        vestine=[_vestina()],
        actor="user:qa",
    )

    izvor = KnowledgeSource.objects.get(title="Izvor za osvežavanje")
    assert izvor.uri == "https://example.com/novo"
    assert izvor.license_box == E.LicenseBox.SLOBODNA.value
    assert izvor.license_note == "MIT"
    assert izvor.commit_sha == "b" * 40
    assert izvor.file_path == "nova/putanja.json"


@requires_db
@pytest.mark.django_db
def test_ponovni_uvoz_sa_praznim_spiskom_ne_dira_ingested_at_ni_trust_score(db):
    """ADR-0095 — osvežavanje pet polja ne dira `ingested_at` (ADR-0076 §2) ni `trust_score`.

    Drugi uvoz šalje PRAZAN spisak veština. Blok iz ADR-0076 §2 koji upisuje
    `ingested_at` se izvršava samo `if vestine:` — sa praznim spiskom se
    uopšte ne izvršava, pa je jedini kod koji sme da dirne red osvežavanje
    pet polja iz ADR-0095. Ako `ingested_at` i `trust_score` posle ovog
    uvoza ostanu nepromenjeni, to stvarno dokazuje da ih osvežavanje pet
    polja ne dira — za razliku od testa sa zamrznutim satom i nepraznim
    spiskom na oba poziva, koji bi prošao i da je osvežavanje pokvarilo to
    polje, jer bi ADR-0076 §2 blok svejedno prepisao `ingested_at` istom
    (zamrznutom) vrednošću.
    """
    uvezi(
        naslov_izvora="Izvor stabilnih polja",
        uri="https://example.com/stabilno-1",
        license_box=E.LicenseBox.NEPOZNATA,
        license_note="",
        vestine=[_vestina()],
        actor="user:qa",
    )
    izvor_pre = KnowledgeSource.objects.get(title="Izvor stabilnih polja")
    ingested_at_pre = izvor_pre.ingested_at
    trust_score_pre = izvor_pre.trust_score
    assert ingested_at_pre is not None

    uvezi(
        naslov_izvora="Izvor stabilnih polja",
        uri="https://example.com/stabilno-2",
        license_box=E.LicenseBox.ZARAZNA,
        license_note="GPL-3.0",
        vestine=[],
        actor="user:qa",
    )

    izvor_posle = KnowledgeSource.objects.get(title="Izvor stabilnih polja")
    assert izvor_posle.ingested_at == ingested_at_pre
    assert izvor_posle.trust_score == trust_score_pre
    # Pet polja se osvežava i kad je spisak veština prazan (ADR-0095) —
    # ovaj uvoz nije "ništa ne radi", samo ne dira pečat ni poverenje.
    assert izvor_posle.uri == "https://example.com/stabilno-2"
    assert izvor_posle.license_box == E.LicenseBox.ZARAZNA.value
    assert izvor_posle.license_note == "GPL-3.0"


@requires_db
@pytest.mark.django_db
def test_prvi_uvoz_pravi_red_sa_svim_vrednostima(db):
    """ADR-0095 — prvi uvoz i dalje pravi nov red sa svim vrednostima, bez regresije."""
    uvezi(
        naslov_izvora="Izvor prvog uvoza",
        uri="https://example.com/prvi",
        license_box=E.LicenseBox.SLOBODNA,
        license_note="MIT",
        commit_sha="c" * 40,
        file_path="putanja/prva.json",
        vestine=[_vestina()],
        actor="user:qa",
    )

    izvor = KnowledgeSource.objects.get(title="Izvor prvog uvoza")
    assert izvor.uri == "https://example.com/prvi"
    assert izvor.license_box == E.LicenseBox.SLOBODNA.value
    assert izvor.license_note == "MIT"
    assert izvor.commit_sha == "c" * 40
    assert izvor.file_path == "putanja/prva.json"
    assert izvor.source_kind == E.SourceKind.FIRST_PARTY_USER_INPUT.value
    assert izvor.trust_score == 1.0
    assert izvor.is_active is True
    assert izvor.ingested_at is not None
