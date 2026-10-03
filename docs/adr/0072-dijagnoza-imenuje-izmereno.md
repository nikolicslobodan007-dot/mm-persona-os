# ADR-0072 — Dijagnoza imenuje izmereno, ne pretpostavljeno

- **Status:** prihvaćen (03.10.2026.)
- **Prethodi:** ADR-0009 (LLM gateway), ADR-0026 (ključ po agentu), ADR-0044
  (pisac), ADR-0050 (pokušaj je zakrpa modela), ADR-0071 (prevod za čoveka),
  ADR-0033 (pravilo nula)
- **Menja:** `apps/orchestration/pisac.py`; dodaje `pisac.zasto_lokalno`
- **Canon:** §6.4, §13

## Šta se desilo

03.10.2026. Pavol (P-00029) je dobio prvi zadatak. `manage.py pisac` je
odgovorio:

> „Zahtev je pao na lokalni šablon, a on ne piše kod. Uključi rutu za
> `code_patch` i LLM_EXTERNAL_ENABLED (ADR-0009)."

Obe stvari koje poruka traži bile su **već uključene**:

| što je poruka tražila | izmereno stanje |
|---|---|
| uključi `LLM_EXTERNAL_ENABLED` | `True` |
| uključi rutu za `code_patch` | postoji i radi — Lazar i Ines su je istog dana koristili |

Pravi razlog je bio treći i poruka ga nije pomenula: **Pavol nema svoj ključ**, a
`LLM_REQUIRE_PERSONA_KEY=True`, pa `credential_ref` vraća prazno i svaka spoljna
ruta otpada (ADR-0026).

Najgore u tome: razlog **nije bio izgubljen**. `gateway._external_allowed` ga
vraća kao šifru, `generate` ga upisuje u `Generation.fallbacks` kao
`provajder/model:NO_PERSONA_KEY`, i taj spisak stiže do `pisac`-a netaknut.
`pisac` ga je bacio i napisao rečenicu iz glave.

## Odluka

### 1. Poruka se sastavlja od izmerenog

`pisac.zasto_lokalno(g.fallbacks)` prevodi svaku preskočenu rutu u razlog, i
poruka kaže samo to:

```
Zahtev je pao na lokalni šablon, a on ne piše kod. Preskočene rute:
anthropic/claude-… — agent nema svoj ključ (konzola → Modeli i ključevi).
```

### 2. Nepoznata šifra prolazi kakva jeste

`_RAZLOG_RUTE` prevodi šifre koje znamo. Šifra koje nema u rečniku se ispisuje
neprevedena. Nepoznata šifra je neprijatna; izmišljen razlog šalje čoveka da
popravlja ono što nije pokvareno — a to se upravo desilo.

### 3. Dijagnoza ne sme da obori ništa

`zasto_lokalno` ne diže izuzetak ni na smeću. Prikaz koji pukne ostavlja čoveka
bez ijednog podatka o kvaru koji ionako gleda (isto pravilo kao `zakrpa.brojke`,
ADR-0071 §5).

### 4. Šta se **ne** menja

Lokalni šablon se i dalje **ne broji kao pokušaj agenta**. `pokusaj` diže
`TaskError` pre nego što išta upiše, pa je Pavol posle ovog poziva ostao na
0/8 pokušaja i 0 centi. To je ADR-0050 i radi kako treba: naš propust u
podešavanju nije agentov neuspeh.

## Šta je odbačeno

- **Da poruka nabraja šta sve može da se uključi.** Rečnik sme da kaže gde se
  ključ postavlja, jer je to jedno mesto i ne menja se. Ali spisak mogućih
  uzroka je upravo ono što je napravilo kvar.
- **Da `pisac` sam proveri ključ pre poziva.** Bila bi to druga kopija pravila
  koje već stoji u `gateway.credential_ref`, i raziđu se prvog dana kad se jedno
  izmeni (isto obrazloženje kao `pisac.pokusaja`, ADR-0071 §4).

## Posledice

- `apps/orchestration/pisac.py` → `zasto_lokalno`, `_RAZLOG_RUTE`; poruka
  `LOCAL_ONLY` se sastavlja iz `Generation.fallbacks`.
- `tests/test_pisac.py` → `TestZastoLokalno`, 6 provera.

## Zapisano za ADR-0033

Tri dana pišem ADR-ove o tome da čovek na kraju lanca mora da dobije činjenice
(ADR-0071), a prva poruka koju je taj isti čovek dobio posle toga bila je
**nagađanje uzroka** — i to nagađanje koje je imalo tačan odgovor u ruci.
`Generation.fallbacks` postoji od ADR-0009.

Pouka nije „bolje formulisati poruke". Pouka je: **kad kod već nosi izmereni
razlog, poruka koja ga ne koristi je laž bez obzira koliko zvuči korisno.**

**Drugo, iz istog sata:** u prvom upisu ove izmene uvukla su mi se dva znaka —
ćirilično `о` usred latinične reči i `ključeveli` umesto `ključevi`. Oba su
prošla kroz `ruff` i kroz `python -c ast.parse` jer su sintaksno ispravna.
Našla ih je provera koja gleda **opseg znakova**, ne sintaksu. Zapisano jer se
isti kvar ne vidi ni u jednom `diff`-u koji čovek čita.
