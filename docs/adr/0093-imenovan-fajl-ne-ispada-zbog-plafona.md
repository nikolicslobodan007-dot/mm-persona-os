# ADR-0093 — Imenovan fajl ne ispada zbog plafona

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Zadatak „KnowledgeSource dobija commit i putanju fajla" tri pokušaja
  zaredom nije doneo testove. Izgledalo je kao da ih agent izostavlja.
- **Prethodi:** ADR-0092, ADR-0084, ADR-0061, ADR-0041 §1, ADR-0033
- **Menja:** `apps/orchestration/brif.py` — `_kandidati` deli kandidate u dve
  grupe. `tests/test_brif.py` — dva nova testa.
- **Canon:** §7.3

## Izmereno

Brif za taj zadatak, 15.10.:

```
truncated: [{'path': 'apps/memory/writer.py', 'reason': 'preko ukupnog plafona (deo zauzela ranija zakrpa)'},
            {'path': 'tests/test_vestine.py', 'reason': 'preko ukupnog plafona (deo zauzela ranija zakrpa)'}]
```

`tests/test_vestine.py` **nije bio u razgovoru**. Agent testove nije izostavio —
nije ih ni imao.

Uzrok je jedan red: `_kandidati` je vraćao `sorted(set(nadjeni))`, dakle čist
azbučni red. `apps/...` stoji pre `tests/...`, pojede plafon, i do imenovanog
fajla se nikad ne dođe.

`allowed_paths` nosi **dve različite stvari**: direktorijum (`apps/memory`) i
tačno imenovan fajl (`tests/test_vestine.py`). Do sada su bile ravnopravne.

## Odluka

Imenovan fajl ide **prvi**. On je čovekov izbor, a ne ulov prefiksa; ako nešto
mora da ispadne zbog plafona, ispada ono što je pokupljeno iz direktorijuma.

Unutar svake od dve grupe red ostaje azbučni, da brif bude ponovljiv.

## Šta se ovim NE menja

Plafon se **ne podiže** (ADR-0041 §1 — zadatak koji probija plafon je preširok,
deli se). Ono što ispadne i dalje ide u `truncated`, naglas.
