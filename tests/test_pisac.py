"""ADR-0044 — model piše zakrpu.

Ovo je jedini deo lanca u kom firma troši novac po pokušaju, pa se ovde brane
tvrdnje o novcu i o zaustavljanju:

  - **plafon i broj pokušaja stvarno zaustavljaju**, a ne samo stoje u ADR-u;
  - **neuspeo poziv se pamti sa troškom.** Poziv koji nije dao diff je plaćen;
    da se prećuti, pokušaji bi bili besplatni i beskonačni;
  - **„nema napretka" staje pre plafona** — ista zakrpa dvaput, ili dve uzastopne
    izmerene zakrpe koje obaraju iste kapije;
  - **lokalni šablon se ne broji kao pokušaj agenta.** On ne piše kod, pa njegov
    odgovor nije agentov neuspeh.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pytest
from django.core.management import call_command

from api.context import bind
from apps.llm_gateway import gateway
from apps.orchestration import pisac, zadaci, zakrpa
from apps.policy import service as policy
from common import enums as E
from tests.conftest import requires_db

pytestmark = [requires_db]

DIFF = ("diff --git a/apps/content/x.py b/apps/content/x.py\n"
        "--- a/apps/content/x.py\n+++ b/apps/content/x.py\n@@ -1 +1 @@\n-a\n+b\n")
DRUGI = DIFF.replace("+b", "+c")
ZONA = ("diff --git a/apps/policy/service.py b/apps/policy/service.py\n"
        "--- a/apps/policy/service.py\n+++ b/apps/policy/service.py\n@@ -1 +1 @@\n-a\n+b\n")


@dataclass
class LazniOdgovor:
    text: str
    provider: str = "anthropic"
    model: str = "claude-proba"
    record: object = None
    input_tokens: int = 100
    output_tokens: int = 50
    amount_eur_cents: int = 7
    fallbacks: tuple = ()


@pytest.fixture
def z(mila):
    with bind(actor_id="user:slobodan"):
        policy.change_trust(mila, "code.write", E.TrustLevel.L1,
                            actor="user:slobodan", reason="p", scope="apps/content")
        return zadaci.create(title="Pisac", why="Provera petlje pisanja.",
                             allowed_paths=["apps/content"], assignee=mila)


@pytest.fixture
def model(monkeypatch):
    """Model koji vraća šta mu se kaže, i broji koliko je puta zvan."""
    stanje = {"pozivi": 0, "odgovor": f"```diff\n{DIFF}```", "cena": 7}

    def lazni(purpose, system, prompt, **kw):
        stanje["pozivi"] += 1
        stanje["prompt"] = prompt
        return LazniOdgovor(text=stanje["odgovor"], amount_eur_cents=stanje["cena"])

    monkeypatch.setattr(gateway, "generate", lazni)
    monkeypatch.setattr(pisac.gateway, "generate", lazni)
    return stanje


@pytest.fixture
def ruta(monkeypatch):
    """Postoji spoljna ruta za `code_patch` — inače pisac s pravom odbija."""
    class R:
        provider = "anthropic"
    monkeypatch.setattr(pisac.gateway, "routes", lambda purpose, persona=None: [R()])


class TestIzvlacenjeDiffa:
    def test_ograda_sa_oznakom(self):
        assert pisac.izvuci_diff(f"Evo:\n```diff\n{DIFF}```\nGotovo.") .startswith(
            "diff --git")

    def test_ograda_bez_oznake(self):
        assert pisac.izvuci_diff(f"```\n{DIFF}```") is not None

    def test_bez_ograde_sece_od_prvog_diff_git(self):
        izvuceno = pisac.izvuci_diff("Uvod koji niko nije tražio.\n" + DIFF)
        assert izvuceno.startswith("diff --git")
        assert "Uvod" not in izvuceno

    @pytest.mark.parametrize("smece", ["", "NE MOGU: nemam fajl models.py",
                                       "```python\nprint(1)\n```", "objašnjenje"])
    def test_ono_sto_nije_diff_se_ne_nagadja(self, smece):
        assert pisac.izvuci_diff(smece) is None

    def test_prvi_blok_koji_lici_na_diff(self):
        tekst = f"```python\nx = 1\n```\n```diff\n{DIFF}```"
        assert pisac.izvuci_diff(tekst).startswith("diff --git")


class TestPokusaj:
    def test_pise_i_predaje(self, z, mila, model, ruta):
        ishod = pisac.pokusaj(z)
        assert ishod.napisano and ishod.status == E.PatchStatus.ACCEPTED.value
        assert ishod.cena_centi == 7 and ishod.potroseno_ukupno == 7
        assert ishod.putanje == ["apps/content/x.py"]
        assert z.patches.count() == 1

    def test_brif_ulazi_u_prompt(self, z, model, ruta):
        pisac.pokusaj(z)
        assert "apps/content" in model["prompt"]
        assert z.public_id in model["prompt"]
        assert "ZAŠTIĆENE ZONE" in model["prompt"]

    def test_zakrpa_u_zonu_se_pamti_kao_odbijena(self, z, model, ruta):
        model["odgovor"] = f"```diff\n{ZONA}```"
        ishod = pisac.pokusaj(z)
        assert not ishod.napisano
        assert z.patches.get().status == E.PatchStatus.REJECTED.value

    def test_odgovor_bez_diffa_je_placen_pokusaj(self, z, model, ruta):
        """Poziv je plaćen i desio se — prećutan bi značio besplatan krug."""
        model["odgovor"] = "NE MOGU: u dozvoljenim putanjama nema tog fajla."
        ishod = pisac.pokusaj(z)
        assert not ishod.napisano and ishod.cena_centi == 7
        red = z.patches.get()
        assert red.status == E.PatchStatus.REJECTED.value
        assert "nije vratio diff" in red.reason
        assert pisac.potroseno(z) == 7

    def test_predugacak_diff_se_odbija(self, z, model, ruta):
        ogroman = DIFF + "".join(f"+red {i}\n" for i in range(9000))
        model["odgovor"] = f"```diff\n{ogroman}```"
        assert not pisac.pokusaj(z).napisano
        assert "podeli zadatak" in z.patches.get().reason


class TestPrekidaci:
    def test_bez_izvrsioca_nema_pisanja(self, mila, db, model, ruta):
        with bind(actor_id="user:slobodan"):
            sam = zadaci.create(title="Bez", why="Nema izvršioca.",
                                allowed_paths=["apps/content"])
        assert "nema izvršioca" in pisac.zasto_ne(sam)

    def test_neizmerena_zakrpa_zadrzava(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, DIFF, persona=mila)
        assert "poslušnik radi" in pisac.zasto_ne(z)

    def test_plafon_pokusaja(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            for d in (DIFF, DRUGI, ZONA):
                p = zakrpa.submit(z, d, persona=mila)
                zadaci.record_gate(z, "pytest", False, patch=p)
        assert "plafon pokušaja (3/3)" in pisac.zasto_ne(z)

    def test_plafon_troska(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, DIFF, persona=mila, cena_centi=60)
            zadaci.record_gate(z, "pytest", False, patch=p)
        assert "potrošeno 60 od 60" in pisac.zasto_ne(z)

    def test_visi_plafon_pusta_dalje(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            p = zakrpa.submit(z, DIFF, persona=mila, cena_centi=60)
            zadaci.record_gate(z, "pytest", False, patch=p)
        assert pisac.zasto_ne(z, plafon_centi=200) is None

    def test_iste_pale_kapije_dvaput_zaustavljaju(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            for d in (DIFF, DRUGI):
                p = zakrpa.submit(z, d, persona=mila)
                zadaci.record_gate(z, "pytest", False, patch=p)
                zadaci.record_gate(z, "ruff", True, patch=p)
        assert "nema napretka" in pisac.zasto_ne(z)

    def test_razlicite_pale_kapije_ne_zaustavljaju(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            p1 = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", False, patch=p1)
            p2 = zakrpa.submit(z, DRUGI, persona=mila)
            zadaci.record_gate(z, "ruff", False, patch=p2)
        assert pisac.zasto_ne(z) is None

    def test_ista_zakrpa_drugi_put_je_neuspeh(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            pp = zakrpa.submit(z, DIFF, persona=mila)
            zadaci.record_gate(z, "pytest", False, patch=pp)
        ishod = pisac.pokusaj(z)          # model vraća isti DIFF
        assert not ishod.napisano
        assert "ista zakrpa" in z.patches.order_by("created_at").last().reason

    def test_zavrsen_zadatak_se_ne_dira(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            for g in z.required_gates:
                zadaci.record_gate(z, g, True)
            zadaci.finish(z)
        assert "DONE" in pisac.zasto_ne(z)

    def test_bez_rute_za_kod_ne_pise(self, z, model, monkeypatch):
        monkeypatch.setattr(pisac.gateway, "routes",
                            lambda purpose, persona=None: [gateway.local_route(purpose)])
        assert "nema rute za pisanje koda" in pisac.zasto_ne(z)

    def test_lokalni_sablon_nije_agentov_neuspeh(self, z, monkeypatch, ruta):
        """Šablon ne piše kod; njegov odgovor se ne upisuje kao pokušaj agenta."""
        monkeypatch.setattr(pisac.gateway, "generate",
                            lambda *a, **k: LazniOdgovor(text="Danas razmišljam…",
                                                         provider="local",
                                                         amount_eur_cents=0))
        with pytest.raises(zadaci.TaskError, match="ne piše kod"):
            pisac.pokusaj(z)
        assert z.patches.count() == 0


class TestUcinakVidiTrosak:
    def test_trosak_je_zbir_zakrpa(self, z, mila, model, ruta):
        from apps.orchestration import ucinak

        pisac.pokusaj(z)
        assert ucinak.za_agenta(mila).trosak_centi == 7

    def test_rucna_zakrpa_ostaje_bez_troska(self, z, mila):
        """Nula bi tvrdila da je model pozvan i da je bio besplatan."""
        from apps.orchestration import ucinak

        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, DIFF, persona=mila)
        assert ucinak.za_agenta(mila).trosak_centi is None

    def test_trosak_vise_nije_na_spisku_neizmerenog(self):
        from apps.orchestration import ucinak

        assert not any("trošak" in s for s in ucinak.NE_MERI_SE)


class TestKomanda:
    def test_zasto_ispisuje_kocnicu(self, z, mila, model, ruta):
        with bind(actor_id="user:slobodan"):
            zakrpa.submit(z, DIFF, persona=mila)
        out = io.StringIO()
        call_command("pisac", "--zadatak", z.public_id, "--zasto", stdout=out)
        assert "ne piše se" in out.getvalue()

    def test_pise_i_javlja_cenu(self, z, model, ruta):
        out = io.StringIO()
        call_command("pisac", "--zadatak", z.public_id, stdout=out)
        ispis = out.getvalue()
        assert "ACCEPTED" in ispis and "7 c" in ispis
        assert "poslušnik je uzima" in ispis

    def test_trazi_tacno_jedan_izbor(self, db):
        from django.core.management import CommandError

        with pytest.raises(CommandError, match="tačno jedno"):
            call_command("pisac", stdout=io.StringIO())
