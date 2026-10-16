"""ADR-0105 — čovekova poruka postaje posao.

Do ovoga je firma imala izlaz (konzola pokazuje šta su agenti uradili), ali
nije imala **ulaz**: posao je počinjao komandom u terminalu. Ovi testovi
proveravaju vrata:

  - razvrstavanje po sektorima radi i kad čovek piše sa dijakritikom;
  - poruka pravi plan direktora, lanac ide naniže i odgovor se vraća u nit;
  - prazna i predugačka poruka se odbijaju pre nego što išta nastane;
  - kad direktor nema koga da zaduži, to se kaže, a ne ćuti.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command

from api.context import bind
from apps.orchestration import razgovor as nit_servis
from apps.orchestration.models import AgentPlan, Poruka, Razgovor
from apps.personas.models import Persona
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]


@pytest.fixture
def firma(db, mila):
    """Organizacija sa direktorom, šefovima i izvršiocima (ADR-0017/0028).

    Spisak ekipe (`apps/personas/ekipa.py`) **nema** `SEF-MKT` ni `URE-SR` —
    izmereno 16.10.2026, Mila i Jovan u produkciji nisu došli odatle. Zato se
    marketing ovde popunjava izričito: inače bi test merio prazan sektor, a
    ne lanac.
    """
    from apps.personas import hiring, org
    from apps.personas.models import Position

    with bind(actor_id="user:qa"):
        call_command("seed_org", stdout=io.StringIO())
        call_command("seed_ekipa", stdout=io.StringIO())
        org.assign(mila, Position.objects.get(code="SEF-MKT"), actor="user:qa")
        hiring.hire(name="Jovan Ilić", position=Position.objects.get(code="URE-SR"),
                    actor="user:qa")
    return Persona.objects.get(assignments__position__code="DIR-00",
                               assignments__ended_at__isnull=True)


@pytest.fixture
def nit(firma):
    return Razgovor.objects.create(persona=firma, human_owner="user:slobodan",
                                   naslov="Proba")


class TestRazvrstavanje:
    """Čista funkcija — bez baze, jer je ovo odluka a ne upit."""

    @pytest.mark.parametrize("tekst,ocekivano", [
        ("Napiši tekst za naslovnu stranu sajta", "MARKETING"),
        ("Proveri šta radi konkurencija na tržištu", "ISTRAZIVANJE"),
        ("Pripremi ponudu za kupca iz Nemačke", "PRODAJA"),
        ("Koliko nas je koštala isporuka prošlog meseca", "LOGISTIKA"),
        ("Razmisli malo o svemu", "UPRAVA"),
    ])
    def test_sektor_po_recima(self, tekst, ocekivano):
        assert nit_servis.odredi_sektor(tekst) == ocekivano

    def test_dijakritika_ne_smeta(self):
        assert nit_servis.odredi_sektor("ISTRAŽI tržište") == "ISTRAZIVANJE"


@pytest.mark.django_db
class TestPorukaPostajePosao:

    def test_odgovor_se_vraca_u_nit_sa_planom(self, nit, firma):
        odgovor = nit_servis.posalji(
            nit, "Napiši kratak tekst o tome čime se bavimo, za sajt.",
            actor="user:slobodan")

        poruke = list(nit.poruke.order_by("created_at"))
        assert len(poruke) == 2
        assert poruke[0].autor == Poruka.OD_COVEKA
        assert poruke[0].autor_ref == "user:slobodan"
        assert poruke[1].autor == Poruka.OD_AGENTA
        assert poruke[1].autor_ref == firma.public_id
        assert odgovor.plan is not None

    def test_posao_je_stvarno_sisao_niz_lanac(self, nit, firma):
        """Direktor ne piše sam: mora da postoji plan nekog drugog agenta."""
        odgovor = nit_servis.posalji(nit, "Napiši tekst za sajt.",
                                     actor="user:slobodan")
        tudji = AgentPlan.objects.exclude(persona=firma)
        assert tudji.exists(), "nijedan agent ispod direktora nije dobio posao"
        assert odgovor.plan.persona_id == firma.pk

    def test_sektor_bez_sefa_ide_upravi_i_to_se_kaze(self, nit, firma):
        """ADR-0105 — nepopunjeno radno mesto ne sme da zaustavi posao."""
        from apps.personas.models import Assignment

        Assignment.objects.filter(position__code="SEF-IST",
                                  ended_at__isnull=True).delete()
        odgovor = nit_servis.posalji(nit, "Istraži šta radi konkurencija.",
                                     actor="user:slobodan")
        assert "ISTRAZIVANJE nema šefa" in odgovor.telo
        assert odgovor.plan is not None

    def test_prazna_poruka_ne_pravi_nista(self, nit):
        with pytest.raises(nit_servis.RazgovorError, match="Prazna"):
            nit_servis.posalji(nit, "   ", actor="user:slobodan")
        assert Poruka.objects.count() == 0
        assert AgentPlan.objects.count() == 0

    def test_preduga_poruka_se_odbija(self, nit):
        with pytest.raises(nit_servis.RazgovorError, match="duža"):
            nit_servis.posalji(nit, "x" * (nit_servis.MAX_TELO + 1),
                               actor="user:slobodan")
        assert Poruka.objects.count() == 0

    def test_bez_potcinjenog_kaze_zasto(self, db, mila):
        """Persona bez organizacije ne može da zada posao — i to se kaže."""
        sama = Razgovor.objects.create(persona=mila, human_owner="user:slobodan")
        with pytest.raises(nit_servis.RazgovorError):
            nit_servis.posalji(sama, "Napiši tekst za sajt.", actor="user:slobodan")

    def test_delegiranje_ne_daje_dozvolu(self, nit, firma):
        """ADR-0017 — posao se spustio, poverenje se nije promenilo."""
        pre = {p.public_id: p.trust_level for p in Persona.objects.all()}
        nit_servis.posalji(nit, "Napiši tekst za sajt.", actor="user:slobodan")
        posle = {p.public_id: p.trust_level for p in Persona.objects.all()}
        assert pre == posle


@requires_db
@pytest.mark.django_db
class TestKonzola:

    @pytest.fixture
    def sef(self, db, firma):
        from django.contrib.auth.models import Group, User

        u = User.objects.create_user("sef105", password="Tajna-lozinka-1")
        u.groups.add(Group.objects.get(name=E.Role.SYSTEM_ADMIN.value))
        u.user_permissions.add(
            *Group.objects.get(name=E.Role.OPERATOR.value).permissions.all())
        call_command("console_totp", user="sef105", stdout=io.StringIO())
        return u

    def _konzola(self, korisnik):
        from django.test import Client

        from tests.test_console import _login

        return _login(Client(), korisnik)

    def test_stranica_pravi_nit_sa_direktorom(self, sef, firma):
        telo = self._konzola(sef).get("/console/razgovor").content.decode()
        assert firma.display_name in telo
        nit = Razgovor.objects.get()
        assert nit.persona_id == firma.pk
        assert nit.human_owner == "user:sef105"

    def test_slanje_iz_konzole_pravi_dve_poruke(self, sef, firma):
        c = self._konzola(sef)
        c.get("/console/razgovor")
        nit = Razgovor.objects.get()
        r = c.post(f"/console/razgovor/{nit.id}/poruka",
                   {"telo": "Napiši tekst za sajt."})
        assert r.status_code == 302
        assert nit.poruke.count() == 2
        telo = c.get(f"/console/razgovor/{nit.id}").content.decode()
        assert "Napiši tekst za sajt." in telo
