"""ADR-0041 — brif za pisca zakrpe.

Brif je građa, ne naredba. Šta se ovde brani:

  - vidi se **samo** ono što je pod dozvoljenim putanjama zadatka;
  - zaštićena zona se ne prikazuje ni kad se nađe pod prefiksom;
  - plafoni stoje, a **ono što je odsečeno se kaže** — pisac mora da zna da nije
    video sve, inače piše nad pretpostavkom (ADR-0033);
  - svaki fajl nosi `sha256`, jer slika nema `.git` pa brif ne tvrdi commit;
  - povratna informacija (otvoreni nalazi, pale kapije) ide uz brif, da sledeći
    pokušaj ne ponovi istu grešku.
"""

from __future__ import annotations

import hashlib

import pytest
from django.urls import reverse

from api.context import bind
from apps.orchestration import brif, zadaci, zakrpa
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

#: Canon §8.5 — svaki zahtev nosi trag i pokretača.
_TRAG = {
    "HTTP_X_REQUEST_ID": "test-brif-0001",
    "HTTP_TRACEPARENT": "00-" + "c" * 32 + "-" + "d" * 16 + "-01",
}


@pytest.fixture
def drugi_agent(db):
    """Recenzent — autor ne piše nalaz na sopstveni rad (ADR-0034 §5.2)."""
    from apps.personas.models import Persona
    return Persona.objects.create(
        public_id="P-09200", display_name="Recenzent",
        persona_type=E.PersonaType.ASSISTANT, status=E.PersonaStatus.ACTIVE,
    )


@pytest.fixture
def poslusnik_klijent(db):
    from django.contrib.auth.models import Group, User
    from rest_framework.authtoken.models import Token
    from rest_framework.test import APIClient

    from api.base import RUNNER_GROUP

    u = User.objects.create_user(username="svc_runner")
    u.groups.set([Group.objects.get_or_create(name=RUNNER_GROUP)[0]])
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}",
                  HTTP_X_ACTOR_ID="service:runner", **_TRAG)
    return c


def _zadatak(putanje, **kw):
    with bind(actor_id="user:slobodan"):
        return zadaci.create(title=kw.pop("title", "Brif"),
                             why=kw.pop("why", "Provera brifa."),
                             allowed_paths=putanje, **kw)


class TestObim:
    def test_vidi_samo_svoje_putanje(self, db):
        b = brif.build(_zadatak(["apps/orchestration"]))
        putanje = {f["path"] for f in b["files"]}
        assert putanje, "prazan brif nije brif"
        assert all(p.startswith("apps/orchestration/") for p in putanje)

    def test_prefiks_u_kom_je_sve_zasticeno_daje_prazan_brif(self, db):
        """Obim u kom je sve zaštićeno — prazno je ISPRAVNO, ali objašnjeno.

        Ranije je ovde stajalo `tools/`, uz pretpostavku da u njemu živi samo
        `canon_lint.py`. Pretpostavka je pala čim je u `tools/pravopis/` stiglo
        nešto što nije kapija (ADR-0055). `policy/` je stabilniji izbor: oba
        fajla u njemu su izričito zaštićena, a sam direktorijum nije — pa
        zadatak sme da se napravi, i tek brif ispadne prazan.
        """
        b = brif.build(_zadatak(["policy"]))
        assert b["files"] == []
        assert b["truncated"], "prazno mora da bude objašnjeno, ne prećutano"

    def test_jedan_fajl_kao_prefiks(self, db):
        b = brif.build(_zadatak(["manage.py"]))
        assert [f["path"] for f in b["files"]] == ["manage.py"]

    def test_zasticena_zona_se_ne_prikazuje(self, db):
        """`tools/` sadrži `canon_lint.py`, koji je zaštićen (ADR-0034 §5.1)."""
        b = brif.build(_zadatak(["tools"]))
        assert "tools/canon_lint.py" not in {f["path"] for f in b["files"]}
        razlozi = {o["path"]: o["reason"] for o in b["truncated"]}
        assert "zaštićena zona" in razlozi["tools/canon_lint.py"]

    def test_putanja_van_korena_se_ignorise(self, db):
        b = brif.build(_zadatak(["../../etc"]))
        assert b["files"] == []

    def test_smece_direktorijumi_se_preskacu(self, db):
        b = brif.build(_zadatak(["apps/orchestration"]))
        assert not any("__pycache__" in f["path"] for f in b["files"])


class TestPlafoni:
    def test_broj_fajlova(self, db, monkeypatch):
        monkeypatch.setattr(brif, "MAX_FILES", 2)
        b = brif.build(_zadatak(["apps/orchestration"]))
        assert len(b["files"]) == 2
        assert any("broja fajlova" in o["reason"] for o in b["truncated"])

    def test_velicina_fajla(self, db, monkeypatch):
        monkeypatch.setattr(brif, "MAX_FILE_BYTES", 200)
        b = brif.build(_zadatak(["apps/orchestration"]))
        assert all(len(f["content"].encode()) <= 200 for f in b["files"])
        assert any("veći od" in o["reason"] for o in b["truncated"])

    def test_ukupna_velicina(self, db, monkeypatch):
        monkeypatch.setattr(brif, "MAX_TOTAL_BYTES", 3000)
        b = brif.build(_zadatak(["apps/orchestration"]))
        assert b["bytes"] <= 3000
        assert any("ukupnog plafona" in o["reason"] for o in b["truncated"])

    def test_odsečeno_se_ne_precutkuje(self, db, monkeypatch):
        """Najvažnija tvrdnja ovog modula: šta je izostavljeno se kaže."""
        monkeypatch.setattr(brif, "MAX_FILES", 1)
        b = brif.build(_zadatak(["apps/orchestration"]))
        assert b["truncated"], "izostavljeno mora da se vidi"
        assert all("path" in o and "reason" in o for o in b["truncated"])


class TestOtisak:
    def test_sha256_odgovara_sadrzaju(self, db):
        b = brif.build(_zadatak(["manage.py"]))
        f = b["files"][0]
        assert f["sha256"] == hashlib.sha256(f["content"].encode()).hexdigest()

    def test_brif_ne_tvrdi_commit(self, db):
        """Slika nema `.git`; obećanje koje ne može da se ispuni se ne daje."""
        assert "base_sha" not in brif.build(_zadatak(["manage.py"]))
        assert "commit" not in brif.build(_zadatak(["manage.py"]))


class TestPovratnaInformacija:
    @pytest.fixture
    def z(self, mila, drugi_agent):
        from apps.policy import service as policy
        with bind(actor_id="user:slobodan"):
            policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                                actor="user:slobodan", reason="p", scope="tools")
            zad = zadaci.create(title="Brif", why="Provera.",
                                allowed_paths=["tools"], assignee=mila)
        return zad

    def test_otvoreni_nalazi_idu_uz_brif(self, z, drugi_agent):
        with bind(actor_id="user:slobodan"):
            zadaci.add_finding(z, reviewer=drugi_agent, file="tools/x.py",
                               line=7, claim="ovde puca na praznom ulazu",
                               severity="MAJOR")
        b = brif.build(z)
        assert b["open_findings"][0]["claim"].startswith("ovde puca")

    def test_zatvoren_nalaz_ne_ide(self, z, drugi_agent):
        with bind(actor_id="user:slobodan"):
            n = zadaci.add_finding(z, reviewer=drugi_agent, file="tools/x.py",
                                   claim="sitnica", severity="NIT")
            n.status = E.FindingStatus.FIXED
            n.save(update_fields=["status"])
        assert brif.build(z)["open_findings"] == []

    def test_pala_kapija_nosi_ispis(self, z):
        with bind(actor_id="user:slobodan"):
            zadaci.record_gate(z, "pytest", False, detail="2 failed, 754 passed")
        pale = brif.build(z)["failed_gates"]
        assert pale[0]["gate"] == "pytest" and "2 failed" in pale[0]["detail"]

    def test_popravljena_kapija_vise_ne_stoji(self, z):
        with bind(actor_id="user:slobodan"):
            zadaci.record_gate(z, "pytest", False, detail="pao")
            zadaci.record_gate(z, "pytest", True)
        assert brif.build(z)["failed_gates"] == []


class TestTacka:
    def test_poslusnik_vidi_brif(self, poslusnik_klijent, db):
        z = _zadatak(["manage.py"])
        o = poslusnik_klijent.get(reverse("task-brief", args=[z.public_id]))
        assert o.status_code == 200
        podaci = o.json()["data"]
        assert podaci["task_id"] == z.public_id
        assert podaci["files"][0]["path"] == "manage.py"
        assert "protected_paths" in podaci

    def test_nepostojeci_zadatak(self, poslusnik_klijent, db):
        assert poslusnik_klijent.get(
            reverse("task-brief", args=["TSK-01M3C15CJ999KE2FX8PG6KHMZE"])
        ).status_code == 404


class TestZakrpaIzBrifa:
    """Brif i kapija za zakrpu moraju da se slažu oko istog pravila putanja."""

    def test_ono_sto_je_u_brifu_sme_da_se_dira(self, mila):
        from apps.policy import service as policy
        with bind(actor_id="user:slobodan"):
            policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                                actor="user:slobodan", reason="p",
                                scope="apps/orchestration")
            z = zadaci.create(title="B", why="p",
                              allowed_paths=["apps/orchestration"], assignee=mila)
        assert brif.build(z)["files"], "prazan brif ne dokazuje ništa"
        for f in brif.build(z)["files"]:
            assert zadaci.may_touch(z, f["path"]) is None, f["path"]


DIFF = ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
        "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n@@ -1 +1 @@\n-a\n+b\n")


def _ogroman(n: int = 9000) -> str:
    """Zakrpa preko plafona, sa **ispravnim** `@@`.

    Do ADR-0049 je ovde stajalo `DIFF + 9000 dodatih redova`, pa je zaglavlje
    tvrdilo `+1` nad telom od 9001 reda. Provera hunkova to sad odbija, a plafon
    se i dalje testira — samo zakrpom koju `git apply` ne bi odbio.
    """
    return ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
            "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n"
            f"@@ -1 +1,{n + 1} @@\n-a\n+b\n"
            + "".join(f"+red {i}\n" for i in range(n)))


@pytest.fixture
def z(mila):
    """Zadatak sa izvršiocem koji sme u `apps/content`."""
    from apps.policy import service as policy

    with bind(actor_id="user:slobodan"):
        policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                            actor="user:slobodan", reason="p", scope="apps/content")
        return zadaci.create(title="Ranija zakrpa", why="Provera ADR-0047.",
                             allowed_paths=["apps/content"], assignee=mila)


class TestRanijaZakrpa:
    """ADR-0047 — brif kaže iz kog stabla su fajlovi i nosi ranije predatu zakrpu.

    Bez toga je brif protivrečan: nalaz opisuje kod koji u priloženim fajlovima
    ne postoji, jer grana nije u slici aplikacije.
    """

    def test_bez_zakrpe_nema_polja(self, z):
        b = brif.build(z)
        assert b["previous_patch"] is None

    def test_nemerena_zakrpa_se_ne_salje(self, z, mila):
        """Zakrpa koju poslušnik još nije izmerio nije ono o čemu su nalazi."""
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, DIFF, persona=mila)
        assert brif.build(z)["previous_patch"] is None

    def test_merena_zakrpa_ulazi_u_brif(self, z, mila):
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=p)
        pz = brif.build(z)["previous_patch"]
        assert pz is not None and pz["diff"] == DIFF
        assert pz["patch_id"] == str(p.pk) and not pz["truncated"]

    def test_poslednja_merena_pobedjuje(self, z, mila):
        with bind(actor_id="user:slobodan"):
            p1 = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", False, patch=p1)
            p2 = zakrpa.submit(z, DIFF.replace("+b", "+c"), persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=p2)
        assert brif.build(z)["previous_patch"]["patch_id"] == str(p2.pk)

    def test_duga_zakrpa_se_sece_i_kaze(self, z, mila):
        ogromna = _ogroman()
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, ogromna, persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=p)
        pz = brif.build(z)["previous_patch"]
        assert pz["truncated"] is True
        assert len(pz["diff"].encode("utf-8")) <= brif.MAX_PATCH_BYTES

    def test_zakrpa_ulazi_u_isti_plafon(self, z, mila):
        """Plafon se ne podiže tiho — zakrpa troši isti budžet kao i fajlovi."""
        bez = brif.build(z)["bytes"]
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=p)
        sa = brif.build(z)
        assert sa["bytes"] == bez + len(DIFF.encode("utf-8"))
        assert sa["bytes"] <= brif.MAX_TOTAL_BYTES

    def test_brif_kaze_iz_kog_stabla_su_fajlovi(self, z):
        poruka = brif.build(z)["files_from"]
        assert "glavnoj grani" in poruka and "NIJE" in poruka

    def test_prompt_nosi_zakrpu_i_upozorenje(self, z, mila):
        from apps.orchestration import pisac

        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=p)
            zadaci.add_finding(z, reviewer=None, file="apps/content/x.py",
                               claim="ćuti o sečenju", severity="BLOCKER",
                               source=zadaci.IZVOR_COVEK)
        tekst, _ = pisac._prompt(z)
        assert "TVOJA RANIJA ZAKRPA" in tekst and DIFF.splitlines()[0] in tekst
        assert "odnose se na OVU zakrpu" in tekst


class TestIshodRanijeZakrpe:
    """ADR-0050 — brif kaže šta se sa ranijom zakrpom STVARNO desilo.

    27.09. je pisac dobio brif u kome je njegova pokvarena zakrpa stajala kao
    `status: ACCEPTED`, nalazi prazni, a jedini prigovor je bio `pytest` sa
    `git` porukom u detalju. Iz takvog brifa je vratio **istu zakrpu** — što je
    koštalo jedan poziv i poslednji pokušaj. `ACCEPTED` znači samo „prošla je
    proveru putanja", i sama ta reč je obmanula.
    """

    def test_neprimenjena_zakrpa_to_kaze(self, z, mila):
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", False, patch=p)
        pz = brif.build(z)["previous_patch"]
        assert pz["status"] == E.PatchStatus.ACCEPTED.value
        assert "NIJE primenjena" in pz["ishod"]
        assert "napiši je iznova" in pz["ishod"]

    def test_primenjena_zakrpa_nosi_commit(self, z, mila):
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=p)
        p.applied_sha = "a" * 40
        p.save(update_fields=["applied_sha"])
        pz = brif.build(z)["previous_patch"]
        assert "primenjena" in pz["ishod"] and "aaaaaaaaaaaa" in pz["ishod"]

    def test_odbijena_zakrpa_stize_sa_razlogom(self, z, mila):
        """Razlog odbijanja je jedino po čemu pisac može da ispravi rad."""
        with bind(actor_id="user:slobodan"):
            zakrpa.zabelezi_neuspeh(z, persona=mila, tekst="nema tu diffa",
                                    razlog="model nije vratio diff: evo popravio sam",
                                    cena_centi=7, od_modela=True)
        pz = brif.build(z)["previous_patch"]
        assert pz is not None, "odbijena zakrpa do ADR-0050 uopšte nije stizala do pisca"
        assert pz["status"] == E.PatchStatus.REJECTED.value
        assert "ODBIJENA" in pz["ishod"]
        assert "nije vratio diff" in pz["ishod"] and "nije vratio diff" in pz["reason"]

    def test_ispravka_zaglavlja_stize_do_pisca(self, z, mila):
        """ADR-0052 — pisac mora da zna da smo mu prebrojali zaglavlje.

        Do ADR-0052 je ovo bilo odbijanje sa porukom; sada je ispravka. U oba
        slučaja važi isto: ono što smo uradili njegovom radu mora da mu se kaže,
        inače sledeći put ponavlja istu grešku uverenim da je sve bilo u redu.
        """
        pokvarena = ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
                     "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n"
                     "@@ -1,1 +1,9 @@\n-a\n+b\n")
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, pokvarena, persona=mila, od_modela=True)
            zadaci.record_gate(z, "pytest", True, patch=p)
        pz = brif.build(z)["previous_patch"]
        assert "ADR-0052" in pz["reason"] and "-1 +9 → -1 +1" in pz["reason"]
        assert "@@ -1,1 +1,1 @@" in pz["diff"]

    def test_neizmerena_i_dalje_ne_ulazi(self, z, mila):
        """Prihvaćena a nemerena zakrpa je posao koji poslušnik tek uzima."""
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, DIFF, persona=mila)
        assert brif.build(z)["previous_patch"] is None

    def test_poslednja_pobedjuje_bez_obzira_na_ishod(self, z, mila):
        with bind(actor_id="user:slobodan"):
            p1 = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", True, patch=p1)
            p2 = zakrpa.zabelezi_neuspeh(z, persona=mila, tekst="proza",
                                         razlog="model nije vratio diff", od_modela=True)
        assert brif.build(z)["previous_patch"]["patch_id"] == str(p2.pk)
