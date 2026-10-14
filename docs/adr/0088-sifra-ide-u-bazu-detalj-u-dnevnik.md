# ADR-0088 — Šifra ide u bazu, detalj ide u dnevnik

- **Status:** prihvaćen (14.10.2026.)
- **Povod:** Šav je proradio do kraja i vratio ime (`PRAZNA_ZAKRPA`), ali ne i
  razlog. Lazar je ispis pokretača stavio u poruku greške, kako je brif tražio;
  gateway tu poruku baci.
- **Prethodi:** ADR-0086 (šav za Aidera), ADR-0087 (zakrpu pravi `git`),
  ADR-0009 (gateway), ADR-0033 (pretpostavka je majka svih zajeba)
- **Menja:** `apps/llm_gateway/gateway.py` — jedan logger i jedna pomoćna
  funkcija; poziv u dve `except LLMError` grane. `tests/test_content.py` — jedan
  test.
- **Canon:** §13, §17

## Izmereno

`LLMError` nosi dva polja: `code` i `detail`. U `generate()`, u grani
`except LLMError as e:`, od cele greške preživi **samo šifra**, na dva mesta:

```
fallbacks.append(f"{route.provider}/{route.model_key}:{e.code}")
_record(..., error=e.code)
```

`PromptRecord.error_code` je `CharField(max_length=80)` — mesta za detalj tamo
nema, i ne treba da ga ima. Isti oblik stoji i u `transcribe()`.

U `apps/llm_gateway/gateway.py` nije bilo nijednog `logging.getLogger`. U celom
projektu postoji **jedan** obrazac: `apps/content/planner.py:11`, oblika
`log = logging.getLogger(__name__)`. Svoj obrazac se ne uvodi.

## Odluka

Detalj ide u **dnevnik**, ne u bazu. `_u_dnevnik(route, e)` piše jedan
`log.warning` sa provajderom, modelom, šifrom i **prvih 2000 znakova** detalja;
bez detalja ne piše ništa. Poziva se u obe `except LLMError` grane, jer je
gubitak detalja isti defekt na oba mesta.

Granica 2000 znakova je ista kao u ADR-0086 — ispis pokretača se tamo seče na
istu meru, pa se dnevnik i poruka greške ne razlikuju.

## Šta se ovim NE menja

U bazi i dalje ostaje samo šifra. Prompt i odgovor se i dalje ne čuvaju kao
tekst, samo hash (Canon §17) — ovo ne otvara nov put za sadržaj prompta u zapis.

Okruženje se **ne piše u dnevnik**. U `env` koji `pisac.py` sastavlja za
pokretač nalazi se ključ persone (`ANTHROPIC_API_KEY`), pa se u dnevnik ide
`e.detail`, nikada `env` i nikada `argv` koji bi ga mogao nositi. Test to ne
proverava — proveravaju ga ove tri reči, i sledeći ko dira ovu funkciju.

Ovaj fajl agentu se ne daje na pisanje: u njemu je `_external_allowed`, tj.
`PROVIDER_MAY_TRAIN`. Pisao ga je vlasnikov sagovornik rukom (ADR-0086).
