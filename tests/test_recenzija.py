"""ADR-0036 — uvoz mašinske recenzije iz SARIF-a.

Oblik izveštaja nije pretpostavljen: preuzet je iz `cmd/opencodereview/sarif.go`
u `alibaba/open-code-review` v1.12.9 — osam kategorija, tri nivoa, otisak pod
ključem `ocrFinding/v1`.

Šta se brani:

  - što nije SARIF, odbija se — tiho uvezenih nula nalaza nema;
  - mašina ne postavlja `BLOCKER`, pa ne zaustavlja zadatak sama;
  - nalaz van dozvoljenih putanja i u zaštićenoj zoni se **ne kači** na zadatak;
  - ponovljen uvoz ne pravi duplikate;
  - kapija `review` ostaje netaknuta.
"""

from __future__ import annotations

import io
import json

import pytest
from django.core.management import CommandError, call_command

from api.context import bind
from apps.orchestration import recenzija as uvoz
from apps.orchestration import zadaci
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]


def _nalaz(putanja, *, nivo="warning", kategorija="bug", tekst="Nešto ne valja.",
           red=40, otisak="fp-1"):
    res = {
        "ruleId": kategorija,
        "level": nivo,
        "message": {"text": tekst},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": putanja},
                "region": {"startLine": red, "endLine": red},
            }
        }],
    }
    if otisak:
        res["partialFingerprints"] = {"ocrFinding/v1": otisak}
    return res


def _izvestaj(*nalazi):
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "OpenCodeReview", "version": "1.12.9",
                "informationUri": "https://github.com/alibaba/open-code-review",
                "rules": [{"id": "bug", "name": "Bug",
                           "shortDescription": {"text": "Defect or logic error"}}],
            }},
            "results": list(nalazi),
        }],
    }


@pytest.fixture
def z(mila):
    with bind(actor_id="user:slobodan"):
        return zadaci.create(
            title="Srpski navodnici", why="Marketing javlja da nacrt gubi navodnike.",
            allowed_paths=["apps/content", "tests/test_content.py"],
        )


def _uvezi(z, izvestaj, **kw):
    with bind(actor_id="user:slobodan"):
        return uvoz.import_sarif(z, izvestaj, **kw)


class TestStrogUlaz:
    @pytest.mark.parametrize("smece", [
        {"results": []},                                   # bez version
        {"version": "1.0.0", "runs": []},                  # pogrešna verzija
        {"version": "2.1.0"},                              # bez runs
        {"version": "2.1.0", "runs": {}},                  # runs nije lista
        {"version": "2.1.0", "runs": [{"results": 5}]},    # results nije lista
        [],                                                # nije objekat
    ])
    def test_sto_nije_sarif_se_odbija(self, z, smece):
        with pytest.raises(uvoz.TaskError) as e:
            _uvezi(z, smece)
        assert e.value.code == "BAD_REPORT"

    def test_prazan_izvestaj_nije_greska(self, z):
        stanje = _uvezi(z, _izvestaj())
        assert stanje["uvezeno"] == 0
        assert stanje["izvor"] == "OpenCodeReview"

    def test_nema_fajla(self):
        with pytest.raises(uvoz.TaskError) as e:
            uvoz.load_sarif("/nema/ovoga.sarif")
        assert e.value.code == "NO_REPORT"


class TestTezina:
    @pytest.mark.parametrize("nivo,ocekivano", [
        ("error", "MAJOR"), ("warning", "MINOR"), ("note", "NIT"),
        ("none", "NIT"), ("", "NIT"), ("izmisljeno", "NIT"),
    ])
    def test_preslikavanje_je_stepen_nize(self, z, nivo, ocekivano):
        _uvezi(z, _izvestaj(_nalaz("apps/content/steps.py", nivo=nivo)))
        assert z.findings.get().severity == ocekivano

    def test_masina_nikad_ne_blokira(self, z):
        """Ni `critical` iz alata ne sme da zaustavi zadatak sam od sebe."""
        _uvezi(z, _izvestaj(
            _nalaz("apps/content/steps.py", nivo="error", kategorija="security",
                   tekst="SQL injection", otisak="fp-sec")))
        assert not zadaci.blocking_findings(z).exists()
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)
            zadaci.finish(z)          # ne pada
        z.refresh_from_db()
        assert z.status == E.TaskStatus.DONE

    def test_izvorna_tezina_se_ne_gubi(self, z):
        _uvezi(z, _izvestaj(_nalaz("apps/content/steps.py", nivo="error",
                                   kategorija="security", tekst="SQL injection")))
        assert "[security/error]" in z.findings.get().claim

    def test_bezbednost_se_prebrojava(self, z):
        stanje = _uvezi(z, _izvestaj(
            _nalaz("apps/content/steps.py", nivo="error", kategorija="security",
                   otisak="a"),
            _nalaz("apps/content/a.py", nivo="error", kategorija="bug", otisak="b"),
            _nalaz("apps/content/b.py", nivo="warning", kategorija="security",
                   otisak="c"),
        ))
        assert stanje["bezbednost"] == 1


class TestGranice:
    def test_van_zadatka_se_ne_kaci(self, z):
        stanje = _uvezi(z, _izvestaj(_nalaz("apps/memory/writer.py")))
        assert stanje["uvezeno"] == 0
        assert stanje["van_zadatka"] == ["apps/memory/writer.py"]
        assert not z.findings.exists()

    def test_zasticena_zona_se_ne_kaci(self, z):
        stanje = _uvezi(z, _izvestaj(_nalaz("apps/policy/service.py", nivo="error")))
        assert stanje["uvezeno"] == 0 and stanje["zasticena_zona"] == [
            "apps/policy/service.py"]

    def test_bez_lokacije_se_prebroji(self, z):
        res = _nalaz("apps/content/steps.py")
        res["locations"] = []
        stanje = _uvezi(z, _izvestaj(res))
        assert stanje["bez_putanje"] == 1 and stanje["uvezeno"] == 0

    def test_putanja_se_normalizuje(self, z):
        _uvezi(z, _izvestaj(_nalaz("./apps/content/steps.py")))
        assert z.findings.get().file == "apps/content/steps.py"

    def test_prefiks_ne_hvata_slicno_ime(self, z):
        stanje = _uvezi(z, _izvestaj(_nalaz("apps/contentx/steps.py")))
        assert stanje["uvezeno"] == 0

    def test_autor_ne_uvozi_recenziju_sebi(self, z, mila):
        z.assignee = mila
        z.save(update_fields=["assignee"])
        with pytest.raises(uvoz.TaskError) as e:
            _uvezi(z, _izvestaj(_nalaz("apps/content/steps.py")), reviewer=mila)
        assert e.value.code == "SELF_REVIEW"


class TestPonovljenUvoz:
    def test_isti_otisak_se_ne_duplira(self, z):
        izvestaj = _izvestaj(_nalaz("apps/content/steps.py", otisak="fp-x"))
        prvi = _uvezi(z, izvestaj)
        drugi = _uvezi(z, izvestaj)
        assert prvi["uvezeno"] == 1 and drugi["uvezeno"] == 0
        assert drugi["vec_postoji"] == 1
        assert z.findings.count() == 1

    def test_duplikat_unutar_istog_izvestaja(self, z):
        stanje = _uvezi(z, _izvestaj(
            _nalaz("apps/content/steps.py", otisak="fp-y"),
            _nalaz("apps/content/steps.py", otisak="fp-y", tekst="isto opet"),
        ))
        assert stanje["uvezeno"] == 1 and stanje["vec_postoji"] == 1

    def test_bez_otiska_se_i_dalje_uvozi(self, z):
        stanje = _uvezi(z, _izvestaj(
            _nalaz("apps/content/steps.py", otisak=""),
            _nalaz("apps/content/a.py", otisak=""),
        ))
        assert stanje["uvezeno"] == 2

    def test_nov_nalaz_u_drugom_krugu_prolazi(self, z):
        _uvezi(z, _izvestaj(_nalaz("apps/content/steps.py", otisak="fp-1")))
        stanje = _uvezi(z, _izvestaj(
            _nalaz("apps/content/steps.py", otisak="fp-1"),
            _nalaz("apps/content/b.py", otisak="fp-2", tekst="nov nalaz"),
        ))
        assert stanje["uvezeno"] == 1 and stanje["vec_postoji"] == 1


class TestKomanda:
    def _fajl(self, tmp_path, izvestaj):
        p = tmp_path / "nalaz.sarif"
        p.write_text(json.dumps(izvestaj), encoding="utf-8")
        return str(p)

    def test_uvoz_i_ispis(self, z, tmp_path):
        put = self._fajl(tmp_path, _izvestaj(
            _nalaz("apps/content/steps.py", otisak="fp-1"),
            _nalaz("apps/policy/service.py", nivo="error", otisak="fp-2"),
        ))
        out = io.StringIO()
        call_command("recenzija", "--zadatak", z.public_id, "--sarif", put, stdout=out)
        ispis = out.getvalue()
        assert "uvezeno:       1" in ispis
        assert "ZAŠTIĆENA ZONA" in ispis and "apps/policy/service.py" in ispis
        assert "nije dirana" in ispis

    def test_kapija_review_ostaje_netaknuta(self, z, tmp_path):
        put = self._fajl(tmp_path, _izvestaj(_nalaz("apps/content/steps.py")))
        call_command("recenzija", "--zadatak", z.public_id, "--sarif", put,
                     stdout=io.StringIO())
        assert not z.gates.filter(gate=E.Gate.REVIEW.value).exists()

    def test_smece_umesto_sarifa(self, z, tmp_path):
        p = tmp_path / "smece.json"
        p.write_text('{"nalazi": []}', encoding="utf-8")
        with pytest.raises(CommandError, match="BAD_REPORT"):
            call_command("recenzija", "--zadatak", z.public_id, "--sarif", str(p),
                         stdout=io.StringIO())

    def test_nepostojeci_zadatak(self, db, tmp_path):
        p = tmp_path / "n.sarif"
        p.write_text(json.dumps(_izvestaj()), encoding="utf-8")
        with pytest.raises(CommandError, match="ne postoji"):
            call_command("recenzija", "--zadatak", "TSK-nema", "--sarif", str(p),
                         stdout=io.StringIO())


class TestPopravkePosleRecenzije:
    """Nalazi mašinske recenzije nad ADR-0035/0036 (25.09.), popravljeni."""

    def test_nalaz_bez_tvrdnje_se_broji(self, z):
        """ADR-0036 §1: tiho ispuštenih nalaza nema — ni onih bez teksta."""
        res = _nalaz("apps/content/steps.py", tekst="")
        stanje = _uvezi(z, _izvestaj(res))
        assert stanje["bez_teksta"] == 1 and stanje["uvezeno"] == 0

    def test_create_sa_izvrsiocem_proverava_poverenje(self, mila):
        """Dodela ima proveru poverenja; `create` je ne sme zaobići."""
        with pytest.raises(zadaci.TaskError) as e, bind(actor_id="user:slobodan"):
            zadaci.create(title="x", why="y", allowed_paths=["apps/content"],
                          assignee=mila)
        assert e.value.code == "TRUST_TOO_LOW"

    def test_create_sa_izvrsiocem_prolazi_kad_poverenje_postoji(self, mila):
        from apps.policy import service as policy
        with bind(actor_id="user:slobodan"):
            policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                                actor="user:slobodan", reason="proba",
                                scope="apps/content")
            z = zadaci.create(title="x", why="y", allowed_paths=["apps/content"],
                              assignee=mila)
        assert z.status == E.TaskStatus.ASSIGNED and z.assignee_id == mila.pk
