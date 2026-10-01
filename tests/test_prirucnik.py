"""ADR-0060 — priručnik radnog mesta.

Brane se tvrdnje koje ADR izgovara, a koje bi bez provere ostale tvrdnje:

  - **pravilo bez izvora ne ulazi** (§3) — i to kao uslov baze, ne kao nada;
  - **ugašeno pravilo nosi razlog i potpis** (ADR-0036 §1) — tiho nestalih
    pravila nema, jer je svako od njih izmena opisa posla;
  - **priručnik visi o mestu, ne o agentu** (§1) — isti tekst vide svi koji
    sede na toj stolici, a ko pređe na drugo mesto vidi drugi;
  - **izvor se čuva, ali ne ide u promptu** (§3, ADR-0063 §2);
  - **odsečeno se kaže** (ADR-0033) — spisak pravila koji je prećutno skraćen
    gori je od kratkog, jer agent po njemu radi kao da je potpun;
  - **upis je idempotentan po ključu** — ispravka formulacije ne pravi duplikat
    i ne gubi istoriju.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command
from django.db.utils import IntegrityError
from django.utils import timezone

from api.context import bind
from apps.personas import prirucnik
from apps.personas.models import (
    Assignment,
    Department,
    Position,
    PositionHandbookRule,
)
from apps.personas.prirucnici import RAZ_PRO
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

ACTOR = "user:slobodan"


@pytest.fixture
def mesto(db):
    d = Department.objects.create(code="RAZVOJ-T", name="Razvoj (test)", sort_order=98)
    return Position.objects.create(
        department=d, code="RAZ-PRO", title="Programer",
        level=E.OrgLevel.MEDIOR, headcount_max=9)


@pytest.fixture
def drugo_mesto(db):
    d = Department.objects.create(code="ISTRAZ-T", name="Istraživanje (test)",
                                  sort_order=97)
    return Position.objects.create(
        department=d, code="IST-ANA", title="Analitičar",
        level=E.OrgLevel.MEDIOR, headcount_max=9)


def _pravila(n: int = 3) -> list[prirucnik.Pravilo]:
    return [prirucnik.Pravilo(f"p{i}", i, f"Pravilo broj {i}.", f"ADR-00{i}")
            for i in range(1, n + 1)]


class TestUpis:
    def test_upisuje_i_broji(self, mesto):
        with bind(actor_id=ACTOR):
            br = prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
        assert br == {"upisano": 3, "izmenjeno": 0, "netaknuto": 0}
        assert PositionHandbookRule.objects.filter(position=mesto).count() == 3

    def test_drugi_upis_ne_pravi_duplikat(self, mesto):
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
            br = prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
        assert br == {"upisano": 0, "izmenjeno": 0, "netaknuto": 3}
        assert PositionHandbookRule.objects.count() == 3

    def test_izmenjen_tekst_se_prepisuje_pod_istim_kljucem(self, mesto):
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
            izmenjeno = _pravila()
            izmenjeno[0] = prirucnik.Pravilo("p1", 1, "Drugačije rečeno.", "ADR-001")
            br = prirucnik.upisi("RAZ-PRO", izmenjeno, actor=ACTOR)
        assert br["izmenjeno"] == 1
        assert PositionHandbookRule.objects.count() == 3
        assert PositionHandbookRule.objects.get(key="p1").text == "Drugačije rečeno."

    def test_pravilo_bez_izvora_se_odbija(self, mesto):
        """ADR-0060 §3 — pravilo koje niko ne može da potkrepi je tvrdnja."""
        with bind(actor_id=ACTOR), pytest.raises(ValueError, match="nema izvor"):
            prirucnik.upisi("RAZ-PRO", [prirucnik.Pravilo("x", 1, "Tekst.", "  ")],
                            actor=ACTOR)

    def test_baza_odbija_prazan_izvor_i_kad_se_zaobidje_servis(self, mesto):
        """Uslov stoji u bazi, ne samo u servisu — servis se da zaobići."""
        with pytest.raises(IntegrityError):
            PositionHandbookRule.objects.create(
                position=mesto, key="bez", text="Tekst.", source="",
                sort_order=1, created_by=ACTOR)

    def test_nepoznato_mesto(self, db):
        with bind(actor_id=ACTOR), pytest.raises(ValueError, match="ne postoji"):
            prirucnik.upisi("NEMA-GA", _pravila(1), actor=ACTOR)


class TestGasenje:
    def test_ugaseno_izlazi_iz_spiska_i_ostaje_u_bazi(self, mesto):
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
            prirucnik.ugasi("RAZ-PRO", "p2", razlog="Pokrila ga kapija.", actor=ACTOR)
        assert [r.key for r in prirucnik.spisak("RAZ-PRO")] == ["p1", "p3"]
        assert len(prirucnik.spisak("RAZ-PRO", i_ugasena=True)) == 3
        r = PositionHandbookRule.objects.get(key="p2")
        assert (r.retired_reason, r.retired_by) == ("Pokrila ga kapija.", ACTOR)

    def test_bez_razloga_se_ne_gasi(self, mesto):
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
            with pytest.raises(ValueError, match="razlog"):
                prirucnik.ugasi("RAZ-PRO", "p1", razlog="   ", actor=ACTOR)

    def test_baza_odbija_ugaseno_bez_razloga(self, mesto):
        """ADR-0036 §1 — tiho ugašenih pravila nema."""
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", _pravila(1), actor=ACTOR)
        r = PositionHandbookRule.objects.get(key="p1")
        r.is_active = False
        with pytest.raises(IntegrityError):
            r.save(update_fields=["is_active"])

    def test_ponovni_upis_vraca_u_zivot_i_brise_razlog(self, mesto):
        """Razlog gašenja uz pravilo koje ponovo važi lagao bi istoriju."""
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
            prirucnik.ugasi("RAZ-PRO", "p1", razlog="Privremeno.", actor=ACTOR)
            prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
        r = PositionHandbookRule.objects.get(key="p1")
        assert (r.is_active, r.retired_reason, r.retired_by) == (True, "", "")

    def test_nepoznat_kljuc(self, mesto):
        with bind(actor_id=ACTOR), pytest.raises(ValueError, match="nema pravilo"):
            prirucnik.ugasi("RAZ-PRO", "nepostojeci", razlog="x", actor=ACTOR)


class TestOdeljakUPromptu:
    def test_redosled_je_onaj_koji_je_upisan(self, mesto):
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", [
                prirucnik.Pravilo("b", 2, "Drugo.", "ADR-1"),
                prirucnik.Pravilo("a", 1, "Prvo.", "ADR-1"),
            ], actor=ACTOR)
        odeljak = prirucnik.prompt_section("RAZ-PRO")
        assert odeljak.index("Prvo.") < odeljak.index("Drugo.")
        assert "1. Prvo." in odeljak and "2. Drugo." in odeljak

    def test_izvor_se_cuva_a_ne_ide_u_prompt(self, mesto):
        """ADR-0063 §2 — agent ne može da otvori `docs/adr/`, pa je citat ukras."""
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", [
                prirucnik.Pravilo("a", 1, "Tekst pravila.", "ADR-0049, ADR-0052"),
            ], actor=ACTOR)
        assert PositionHandbookRule.objects.get(key="a").source == "ADR-0049, ADR-0052"
        assert "ADR-0049" not in prirucnik.prompt_section("RAZ-PRO")

    def test_ugaseno_pravilo_ne_stize_do_modela(self, mesto):
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", _pravila(), actor=ACTOR)
            prirucnik.ugasi("RAZ-PRO", "p2", razlog="Ne važi više.", actor=ACTOR)
        assert "Pravilo broj 2." not in prirucnik.prompt_section("RAZ-PRO")

    def test_bez_pravila_nema_odeljka(self, mesto):
        assert prirucnik.prompt_section("RAZ-PRO") == ""

    def test_odsecanje_se_kaze_i_staje_u_budzet(self, mesto):
        """Rezerva za red o odsecanju mora da bude UNUTAR budžeta, ne pored.

        Isti kvar je kod pouka bio uhvaćen u ADR-0054: red koji se dopiše na
        kraju probije granicu koju je punjenje tek ispoštovalo.
        """
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", _pravila(10), actor=ACTOR)
        odeljak = prirucnik.prompt_section("RAZ-PRO", budzet=120)
        assert "odsečeno" in odeljak
        assert len(odeljak) <= 120
        assert "Pravilo broj 10." not in odeljak


class TestVezaSaAgentom:
    def test_mesto_persone_je_otvoren_primarni_raspored(self, mesto, mila):
        assert prirucnik.mesto_persone(mila) is None
        Assignment.objects.create(persona=mila, position=mesto,
                                  started_at=timezone.now())
        assert prirucnik.mesto_persone(mila) == "RAZ-PRO"

    def test_zavrsen_raspored_ne_daje_prirucnik(self, mesto, mila):
        a = Assignment.objects.create(persona=mila, position=mesto,
                                      started_at=timezone.now())
        a.ended_at = timezone.now()
        a.save(update_fields=["ended_at"])
        assert prirucnik.mesto_persone(mila) is None

    def test_prelazak_na_drugo_mesto_menja_prirucnik(self, mesto, drugo_mesto, mila):
        """ADR-0060 §1 — priručnik visi o stolici, ne o agentu."""
        with bind(actor_id=ACTOR):
            prirucnik.upisi("RAZ-PRO", [
                prirucnik.Pravilo("k", 1, "Ovde se piše zakrpa.", "ADR-0038")],
                actor=ACTOR)
            prirucnik.upisi("IST-ANA", [
                prirucnik.Pravilo("k", 1, "Ovde se izviđa.", "ADR-0059")], actor=ACTOR)
        a = Assignment.objects.create(persona=mila, position=mesto,
                                      started_at=timezone.now())
        assert "zakrpa" in prirucnik.prompt_section(prirucnik.mesto_persone(mila))
        a.ended_at = timezone.now()
        a.save(update_fields=["ended_at"])
        Assignment.objects.create(persona=mila, position=drugo_mesto,
                                  started_at=timezone.now())
        assert "izviđa" in prirucnik.prompt_section(prirucnik.mesto_persone(mila))


class TestJezgroRazPro:
    def test_svako_pravilo_ima_izvor(self):
        assert all(p.izvor.strip() for p in RAZ_PRO)

    def test_kljucevi_su_jedinstveni(self):
        assert len({p.kljuc for p in RAZ_PRO}) == len(RAZ_PRO)

    def test_redosled_je_neprekidan(self):
        assert [p.redosled for p in RAZ_PRO] == list(range(1, len(RAZ_PRO) + 1))

    def test_jezgro_staje_u_budzet(self):
        """ADR-0060 §2: ako jezgro ne stane, ne raste budžet nego se seče jezgro.

        Izmereno 01.10.2026.: 14 pravila, **1495 znakova** od 3000 (49,8 %),
        1551 bajt = 0,78 % plafona brifa. Ova provera pada kad jezgro naraste
        preko granice — i to je trenutak za sečenje, ne za podizanje.
        """
        naslov = prirucnik.NASLOV.format(mesto="RAZ-PRO")
        tekst = "\n".join([naslov] + [f"{i}. {p.tekst}"
                                      for i, p in enumerate(RAZ_PRO, 1)])
        assert len(tekst) <= prirucnik.PRIRUCNIK_BUDGET_CHARS

    def test_jezgro_ne_ponavlja_ono_sto_brif_ionako_nosi(self):
        """Dozvoljene putanje, zaštićene zone i ishod prethodne zakrpe su
        činjenice zadatka i stoje u brifu po zadatku. Priručnik koji ih ponavlja
        troši budžet na tekst koji model već ima dva puta.
        """
        spojeno = " ".join(p.tekst for p in RAZ_PRO)
        assert "SMEŠ DA DIRAŠ SAMO" in spojeno          # pominje se kao pojam…
        assert spojeno.count("SMEŠ DA DIRAŠ SAMO") == 1  # …ali se spisak ne prepisuje


class TestStizeDoModela:
    """ADR-0050 je napisan zato što je izmena jednom bila samo u sloju koji je
    zgodan za proveru. Zato se ovde meri **prompt koji odlazi modelu**, ne samo
    `prompt_section` i ne samo rečnik brifa.
    """

    @pytest.fixture
    def zadatak(self, mesto, mila):
        from apps.orchestration import zadaci
        from apps.policy import service as policy

        Assignment.objects.create(persona=mila, position=mesto,
                                  started_at=timezone.now())
        with bind(actor_id=ACTOR):
            policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                                actor=ACTOR, reason="p", scope="apps/content")
            prirucnik.upisi("RAZ-PRO", RAZ_PRO, actor=ACTOR)
            return zadaci.create(title="Proba priručnika", why="ADR-0060.",
                                 allowed_paths=["apps/content"], assignee=mila)

    def test_prirucnik_je_u_brifu(self, zadatak):
        from apps.orchestration import brif

        b = brif.build(zadatak)
        assert b["handbook_position"] == "RAZ-PRO"
        assert "Ne pogađaj." in b["handbook"]

    def test_prirucnik_je_u_promptu_bez_izvora(self, zadatak):
        from apps.orchestration import pisac

        tekst, _ = pisac._prompt(zadatak)
        assert "priručnik radnog mesta RAZ-PRO" in tekst
        assert "Ne pogađaj." in tekst
        assert "ADR-0048" not in tekst

    def test_agent_bez_rasporeda_dobija_prompt_bez_prirucnika(self, zadatak, mila):
        """Nema rasporeda — nema stolice, pa nema ni priručnika. Ne pada."""
        from apps.orchestration import pisac

        mila.assignments.update(ended_at=timezone.now())
        tekst, b = pisac._prompt(zadatak)
        assert b["handbook"] == "" and b["handbook_position"] == ""
        assert "priručnik radnog mesta" not in tekst


class TestKomanda:
    def test_upisi_pa_spisak(self, mesto):
        call_command("prirucnik", "--mesto", "RAZ-PRO", "--upisi", stdout=io.StringIO())
        izlaz = io.StringIO()
        call_command("prirucnik", "--mesto", "RAZ-PRO", "--spisak", stdout=izlaz)
        tekst = izlaz.getvalue()
        assert "zakrpa-ne-fajl" in tekst
        assert "ADR-0038" in tekst          # izvor se vidi čoveku…
        assert "aktivno" in tekst

    def test_prompt_ne_pokazuje_izvor(self, mesto):
        call_command("prirucnik", "--mesto", "RAZ-PRO", "--upisi", stdout=io.StringIO())
        izlaz = io.StringIO()
        call_command("prirucnik", "--mesto", "RAZ-PRO", "--prompt", stdout=izlaz)
        assert "ADR-0038" not in izlaz.getvalue()   # …a modelu ne

    def test_trazi_tacno_jedan_izbor(self, mesto):
        with pytest.raises(CommandError, match="tačno jedno"):
            call_command("prirucnik", "--mesto", "RAZ-PRO", "--upisi", "--spisak")

    def test_actor_mora_biti_covek(self, mesto):
        with pytest.raises(CommandError, match="user:"):
            call_command("prirucnik", "--mesto", "RAZ-PRO", "--upisi",
                         "--actor", "persona:P-00027")

    def test_gasenje_trazi_razlog(self, mesto):
        call_command("prirucnik", "--mesto", "RAZ-PRO", "--upisi", stdout=io.StringIO())
        with pytest.raises(CommandError, match="--zasto"):
            call_command("prirucnik", "--mesto", "RAZ-PRO", "--ugasi", "nov-fajl")

    def test_mesto_bez_napisanog_jezgra(self, drugo_mesto):
        with pytest.raises(CommandError, match="nije napisano jezgro"):
            call_command("prirucnik", "--mesto", "IST-ANA", "--upisi")


def test_nepostojeca_persona_nema_mesto():
    assert prirucnik.mesto_persone(None) is None
