"""ADR-0138 — hirurška dozvola za spoljne akcije (external_live). Bez baze."""

from __future__ import annotations

from types import SimpleNamespace

from django.test import override_settings

from apps.policy import gateway
from common import enums as E

ŽIVO = E.RuntimeEnvironment.CONTROLLED_LIVE.value


def _akcija(tip="channel.post.create", persona_id="P-00001", env=ŽIVO,
            kanal=None):
    persona = SimpleNamespace(runtime_environment=env, public_id=persona_id)
    ch = None
    if kanal is not None:
        ct, _, h = kanal.partition(":")
        ch = SimpleNamespace(channel_type=ct, handle=h)
    return SimpleNamespace(persona=persona, action_type=tip, channel_account=ch)


def test_parsiranje_i_poklapanje():
    pravila = gateway._parsiraj_dozvolu(
        "P-00001|telegram:wk_ivana|channel.post.create, P-00002|*|*")
    assert len(pravila) == 2
    a = _akcija(kanal="telegram:wk_ivana")
    assert gateway._poklapa(pravila[0], a) is True
    assert gateway._poklapa(pravila[1], a) is False  # druga persona


@override_settings(GLOBAL_EXTERNAL_ACTIONS_ENABLED=True, EXTERNAL_ACTIONS_ALLOWLIST="")
def test_prazna_lista_kao_do_sada():
    # prazna lista → prekidač je jedini uslov (nepromenjeno, stari testovi žive)
    assert gateway.external_live(_akcija()) is True


@override_settings(GLOBAL_EXTERNAL_ACTIONS_ENABLED=True,
                   EXTERNAL_ACTIONS_ALLOWLIST="P-00099|*|channel.post.create")
def test_neuvrstena_akcija_ne_izlazi():
    assert gateway.external_live(_akcija()) is False  # P-00001 nije na listi


@override_settings(GLOBAL_EXTERNAL_ACTIONS_ENABLED=True,
                   EXTERNAL_ACTIONS_ALLOWLIST="P-00001|*|channel.post.create")
def test_uvrstena_akcija_izlazi():
    assert gateway.external_live(_akcija()) is True


@override_settings(GLOBAL_EXTERNAL_ACTIONS_ENABLED=True,
                   EXTERNAL_ACTIONS_ALLOWLIST="P-00001|telegram:wk_ivana|channel.post.create")
def test_pogresan_kanal_ne_izlazi():
    assert gateway.external_live(_akcija(kanal="x:mila")) is False


@override_settings(GLOBAL_EXTERNAL_ACTIONS_ENABLED=True,
                   EXTERNAL_ACTIONS_ALLOWLIST="P-00099|*|channel.post.create")
def test_citanje_izuzeto_od_liste():
    # čitanje nije u hirurškoj listi (niskorizično) — prolazi kad je prekidač ON
    assert gateway.external_live(_akcija(tip="browser.page.read")) is True


@override_settings(GLOBAL_EXTERNAL_ACTIONS_ENABLED=True,
                   EXTERNAL_ACTIONS_ALLOWLIST="P-00001|*|channel.post.create")
def test_simulacija_nikad_ne_izlazi():
    # persona van živog okruženja → False bez obzira na listu i prekidač
    a = _akcija(env=E.RuntimeEnvironment.SIMULATION.value)
    assert gateway.external_live(a) is False
