# ADR-0035 — Model zadatka

- **Status:** prihvaćen (25.09.2026.)
- **Prethodi:** ADR-0034 (departman za programiranje), ADR-0033 (pravilo nula),
  ADR-0021 (plan), ADR-0022 (delegiranje)
- **Canon:** §2.2 (public_id kroz ADR), §3 (katalog enum-a), §16.5 (audit)

## Zašto

ADR-0034 je rekao da je jedinica posla **zadatak**: šta, zašto, koje fajlove sme da
dira i šta znači gotovo. Dok toga nema, programerski agent ima samo poverenje po
opsegu (ADR-0034 §2) — a to kaže gde *sme*, ne šta *treba*. Bez zadatka nema ni
merenja iz §6 tog ADR-a, jer se nema šta izbrojati.

## Odluka

### 1. `CodeTask` — jedan red, četiri obaveze

| Polje | Čemu služi |
|---|---|
| `title`, `why` | šta i zašto — poslovni razlog, ne rešenje (ADR-0034 §4) |
| `adr` | veza na odluku; prazno samo za popravke koje ne menjaju odluku |
| `allowed_paths` | **spisak dozvoljenih prefiksa. Ne sme biti prazan.** |
| `required_gates` | šta mora da bude zeleno da bi zadatak bio gotov |
| `assignee`, `reviewer` | ko piše i ko recenzira — **nikad isti** |

Prazan spisak putanja se odbija namerno. Prazno bi značilo „svuda", a zadatak bez
granice je isto što i agent bez granice.

### 2. Dve provere pre svakog dodira fajla

```
sme(zadatak, putanja) =
    putanja nije zaštićena zona      (ADR-0034 §5.1, tvrdo)
  ∧ putanja je pod dozvoljenim prefiksom  (ovaj zadatak)
  ∧ poverenje(agent, code.write, putanja) ≥ L1   (ADR-0034 §2)
```

Tri nezavisne provere, i sve tri moraju da prođu. Zaštićena zona je prva jer se ne
otvara ni zadatkom ni nivoom: zadatak koji navede zaštićenu putanju ne postaje
poluvažeći, nego se **ne pravi**.

### 3. Gotovo je merenje, ne tvrdnja

`GateResult` je zapis jedne kapije nad jednim zadatkom: koja, prošla ili nije, kratak
ispis, kad. Zadatak prelazi u `DONE` samo ako **svaka** tražena kapija ima zelen
zapis i nema otvorenog nalaza težine `BLOCKER`. Agent ne može da zatvori zadatak
rečima — `finish()` odbija.

Kapije: `pytest`, `ruff`, `canon_lint`, `migrations`, `review`. Prve četiri su
mašinske i danas ih vrtimo rukom; `review` je ljudska ili recenzentova.

### 4. Recenzija je nalaz, ne proza

`ReviewFinding`: fajl, linija, tvrdnja, težina (`BLOCKER`/`MAJOR`/`MINOR`/`NIT`),
stanje (`OPEN`/`ACCEPTED`/`REJECTED`/`FIXED`). Nalaz upisuje neko ko nije autor —
baza to sprovodi, ne servis. Ovako se recenzija broji po agentu (ADR-0034 §6) i tako
mašina može da postupi po njoj.

### 5. Deseti oblik `public_id`

Zadatak dobija `TSK-` + ULID. Canon §2.2 to izričito dopušta: „`public_id` se dodaje
tek kada se entitet pojavi u UI-ju ili u razgovoru sa operatorom, i tada kroz ADR."
Zadatak je upravo to — o njemu se razgovara sa operatorom. Canon §2.2 tabela dobija
deseti red; §20 ostaje kakav jeste, jer je definicija gotovog za F0, a ne spisak.

### 6. Bez novih eventa na magistrali

Trag ide u audit (`task.created`, `task.assigned`, `task.gate.recorded`,
`task.finding.added`, `task.finished`), ne u event bus. Katalog eventa je Canon §7.2
i menja se samo kad neko spolja treba da sluša; ovde niko ne sluša.

## Šta je odbačeno

- **Zadatak bez spiska fajlova**, „pa ćemo videti". To je opis posla, ne zadatak.
- **Da servis proverava „recenzent nije autor"**. Proverava baza. Servis se zaobilazi
  jednim `objects.create`.
- **Slobodan tekst recenzije.** Ne broji se, pa se ne može meriti.
- **Da zadatak sam sebi bira kapije naniže.** Podrazumevane su sve četiri mašinske;
  skidanje kapije je izmena zadatka i vidi se u auditu.

## Posledice

- `common/enums.py`: `TaskStatus`, `Gate`, `FindingSeverity`, `FindingStatus`.
- `common/ids.py`: `TSK-`; test broja entiteta se izvodi iz `SPECS`, ne iz konstante.
- `apps/orchestration/zadaci.py` — servis; `manage.py zadatak` — komanda.
- Sledeći korak: `open-code-review` kao prva kapija recenzenta (ADR-0032).
