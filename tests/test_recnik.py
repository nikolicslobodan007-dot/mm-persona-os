"""ADR-0055 — Rečnik uz Pravopis kao znanje i kao provera nad nacrtom.

Rečnik ne ide u prompt: 8.797 odrednica se ne plaća po pozivu. Radi na izlazu,
nad oblicima koje knjiga izričito odbija, i svaki nalaz nosi odrednicu i broj
tačke — ili nema broj tačke, kad se iz skena nije mogao pouzdano pročitati.
"""

from __future__ import annotations

import io
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.content import recnik
from apps.memory.models import KnowledgeFact, KnowledgeSource

ODREDNICE = [
    {"odrednica": "avlija", "odrednica_cir": "авлија",
     "tekst": "avlija (ne havlija)", "tekst_cir": "авлија (не хавлија)",
     "tacke": [], "strana_pdf": 334, "ne": ["havlija"]},
    {"odrednica": "kruška", "odrednica_cir": "крушка",
     "tekst": "kruška, dat. krušci, gen mn. krušaka, t. 86d",
     "tekst_cir": "крушка, дат. крушци, ген мн. крушака, т. 86d",
     "tacke": ["86d"], "strana_pdf": 400, "ne": []},
    {"odrednica": "kubanska revolucija", "odrednica_cir": "кубанска револуција",
     "tekst": "kubanska revolucija, t. [nejasno: 276 ili 27b]",
     "tekst_cir": "кубанска револуција, т. 276",
     "tacke": [], "strana_pdf": 400, "ne": []},
    {"odrednica": "đačko", "odrednica_cir": "ђачко",
     "tekst": "đačko doba (ne djačko)", "tekst_cir": "ђачко доба",
     "tacke": ["81a"], "strana_pdf": 360, "ne": ["djačko"]},
    {"odrednica": "Koraks", "odrednica_cir": "Коракс",
     "tekst": "Koraks (ne Korak), t. 97c", "tekst_cir": "Коракс (не Корак), т. 97c",
     "tacke": ["97c"], "strana_pdf": 398, "ne": ["Korak"]},
    {"odrednica": "podići", "odrednica_cir": "подићи",
     "tekst": "podići, podiđem, bolje nego podaći",
     "tekst_cir": "подићи, подиђем, боље него подаћи",
     "tacke": [], "strana_pdf": 430, "ne": ["podaći"]},
]


@pytest.fixture
def datoteka(tmp_path):
    p = tmp_path / "recnik.jsonl"
    p.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in ODREDNICE),
                 encoding="utf-8")
    return p


@pytest.fixture
def uvezen(db, datoteka):
    recnik.uvezi(putanja=datoteka)
    return datoteka


class TestUvoz:
    def test_pravi_jedan_deljen_izvor(self, db, datoteka):
        recnik.uvezi(putanja=datoteka)
        izvori = KnowledgeSource.objects.filter(title=recnik.IZVOR)
        assert izvori.count() == 1
        assert izvori.first().persona is None, "Rečnik važi za sve agente"

    def test_upisuje_sve_odrednice(self, db, datoteka):
        br = recnik.uvezi(putanja=datoteka)
        assert br["upisano"] == len(ODREDNICE)
        assert KnowledgeFact.objects.filter(predicate=recnik.PREDIKAT).count() == len(ODREDNICE)

    def test_ponovni_uvoz_ne_duplira(self, db, datoteka):
        recnik.uvezi(putanja=datoteka)
        br = recnik.uvezi(putanja=datoteka)
        assert br["obrisano"] == len(ODREDNICE)
        assert KnowledgeFact.objects.filter(predicate=recnik.PREDIKAT).count() == len(ODREDNICE)
        assert KnowledgeSource.objects.filter(title=recnik.IZVOR).count() == 1

    def test_odrednica_nosi_stranu_i_cirilicu(self, db, uvezen):
        f = KnowledgeFact.objects.get(subject="kruška")
        assert f.object_json["strana"] == 400
        assert f.object_json["odrednica_cir"] == "крушка"
        assert f.object_json["tacke"] == ["86d"]

    def test_uvoz_se_zapisuje(self, db, datoteka):
        from apps.observability.models import AuditEvent
        recnik.uvezi(putanja=datoteka)
        red = AuditEvent.objects.filter(event_key="content.recnik.loaded").first()
        assert red is not None
        assert red.payload["details"]["upisano"] == len(ODREDNICE)


class TestBrojTacke:
    def test_nejasno_upucivanje_nema_broj_tacke(self, db, uvezen):
        """Knjiga piše „т. 27b", OCR daje „т. 276", a 276 je druga tačka."""
        f = KnowledgeFact.objects.get(subject="kubanska revolucija")
        assert f.object_json["tacke"] == []
        assert "nejasno" in f.object_json["tekst"]

    def test_isporucena_datoteka_ne_nosi_tacku_van_opsega(self):
        """Deo PRAVILA ide do tačke 322; veće bi bilo izmišljeno."""
        redovi = [json.loads(r) for r in
                  recnik.DATOTEKA.read_text(encoding="utf-8").splitlines() if r]
        assert len(redovi) > 8000, "isporučena datoteka je osiromašena"
        for r in redovi:
            for t in r["tacke"]:
                broj = int("".join(z for z in t if z.isdigit()))
                assert 1 <= broj <= 322, f"{r['odrednica']}: t. {t}"

    def test_isporucena_datoteka_ne_ostavlja_sirovo_nejasno(self):
        """Gde tačka nije pouzdana, u tekstu piše da nije — ne ćuti se."""
        redovi = [json.loads(r) for r in
                  recnik.DATOTEKA.read_text(encoding="utf-8").splitlines() if r]
        nejasnih = [r for r in redovi if "nejasno" in r["tekst"]]
        assert nejasnih, "očekivano je da neka upućivanja ostanu nerazrešena"
        assert all(not r["tacke"] or "nejasno" in r["tekst"] for r in nejasnih)


class TestTrazenje:
    def test_nadje_tacnu_rec(self, db, uvezen):
        assert recnik.nadji("kruška")[0]["odrednica"] == "kruška"

    def test_ne_razlikuje_velika_slova(self, db, uvezen):
        assert recnik.nadji("KRUŠKA")[0]["odrednica"] == "kruška"

    def test_nadje_po_pocetku(self, db, uvezen):
        assert any(p["odrednica"] == "kubanska revolucija"
                   for p in recnik.nadji("kubanska"))

    def test_nepoznata_rec_daje_prazno(self, db, uvezen):
        assert recnik.nadji("xyzw") == []

    def test_prazan_upit_ne_vraca_ceo_recnik(self, db, uvezen):
        assert recnik.nadji("   ") == []


class TestProvera:
    def test_nalazi_odbijen_oblik(self, db, uvezen):
        nalazi = recnik.proveri("Ušao je u havliju i seo.")
        assert len(nalazi) == 1
        assert nalazi[0].odrednica == "avlija"

    def test_uz_nalaz_ide_odrednica_i_tacka(self, db, uvezen):
        nalaz = recnik.proveri("To je djačko doba.")[0]
        assert "Pravopis, t. 81a" in str(nalaz)
        assert nalaz.oblik == "djačko"

    def test_bez_broja_tacke_nema_lažnog_upucivanja(self, db, uvezen):
        nalaz = recnik.proveri("havlija")[0]
        assert "Pravopis" not in str(nalaz), "odrednica bez tačke ne sme da je izmisli"

    def test_ispravan_tekst_prolazi(self, db, uvezen):
        assert recnik.proveri("Ušao je u avliju i seo pod krušku.") == []

    def test_isti_oblik_se_prijavljuje_jednom(self, db, uvezen):
        assert len(recnik.proveri("havlija, havlija, havlija")) == 1

    def test_prazan_tekst_ne_puca(self, db, uvezen):
        assert recnik.proveri("") == []

    def test_hvata_i_promenjen_oblik(self, db, uvezen):
        """Rečnik daje nominativ, a u rečenici reč stoji u padežu."""
        assert recnik.proveri("Ušao je u havliju.")[0].odrednica == "avlija"
        assert recnik.proveri("Iz havlije se čulo.")[0].odrednica == "avlija"

    def test_kvacica_razlikuje_reci(self, db, uvezen):
        """"podaci" nije „podaći" — razlika je baš u kvačici."""
        assert recnik.proveri("Podaci su stigli.") == []
        assert recnik.proveri("Hteo je to podaći.")[0].odrednica == "podići"

    def test_ime_se_prijavljuje_samo_velikim_slovom(self, db, uvezen):
        """„Koraks (ne Korak)" je o prezimenu — ne o reči korak."""
        assert recnik.proveri("Napravio je korak napred.") == []
        assert recnik.proveri("Zvao se Korak.")[0].odrednica == "Koraks"


class TestUtisavanje:
    def test_utisan_oblik_se_vise_ne_prijavljuje(self, db, uvezen):
        assert recnik.proveri("Ušao je u havliju.")
        recnik.utisaj("havlija", actor="user:slobodan", razlog="klijent tako piše")
        assert recnik.proveri("Ušao je u havliju.") == []

    def test_odrednica_ostaje_netaknuta(self, db, uvezen):
        recnik.utisaj("havlija", actor="user:slobodan", razlog="klijent tako piše")
        f = KnowledgeFact.objects.get(subject="avlija")
        assert f.object_json["ne"] == ["havlija"], "knjiga se ne prepravlja"
        assert f.object_json["tiho"] == ["havlija"]

    def test_bez_razloga_se_ne_utisava(self, db, uvezen):
        with pytest.raises(ValueError, match="razlog"):
            recnik.utisaj("havlija", actor="user:slobodan", razlog="  ")

    def test_utisavanje_se_zapisuje(self, db, uvezen):
        from apps.observability.models import AuditEvent
        recnik.utisaj("havlija", actor="user:slobodan", razlog="klijent tako piše")
        red = AuditEvent.objects.filter(event_key="content.recnik.form_silenced").first()
        assert red is not None and red.payload["details"]["oblik"] == "havlija"

    def test_komanda_trazi_razlog(self, db, uvezen):
        with pytest.raises(CommandError, match="zasto"):
            call_command("recnik", "--utisaj", "havlija", stdout=io.StringIO())

    def test_komanda_odbija_nepostojeci_oblik(self, db, uvezen):
        with pytest.raises(CommandError, match="nije ni bio"):
            call_command("recnik", "--utisaj", "xyzw", "--zasto", "r",
                         stdout=io.StringIO())


class TestKomanda:
    def test_stanje_kaze_kad_nije_uvezeno(self, db):
        out = io.StringIO()
        call_command("recnik", "--stanje", stdout=out)
        assert "nije uvezen" in out.getvalue()

    def test_nadji_ispisuje_odrednicu(self, db, uvezen):
        out = io.StringIO()
        call_command("recnik", "--nadji", "kruška", stdout=out)
        assert "86d" in out.getvalue() and "krušci" in out.getvalue()

    def test_proveri_ispisuje_nalaz(self, db, uvezen):
        out = io.StringIO()
        call_command("recnik", "--proveri", "Ušao je u havliju.", stdout=out)
        assert "avlija" in out.getvalue()

    def test_masina_ne_uvozi(self, db):
        with pytest.raises(CommandError, match="user:"):
            call_command("recnik", "--uvezi", "--actor", "service:runner",
                         stdout=io.StringIO())

    def test_trazi_tacno_jedan_zadatak(self, db):
        with pytest.raises(CommandError, match="tačno jedno"):
            call_command("recnik", "--stanje", "--nadji", "avlija", stdout=io.StringIO())
