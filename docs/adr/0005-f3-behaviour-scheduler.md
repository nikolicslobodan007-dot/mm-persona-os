# ADR-0005 — F3: Behaviour engine, rutine, scheduler i World Engine

- **Status:** prihvaćeno
- **Datum:** 21.09.2026.
- **Canon verzija:** 1.1
- **Izvor:** MM Persona OS — Behaviour + World + Scheduler Engine v0.1 (Faza 8)
- **Kod:** `apps/behaviour/{clock,reducer,routines,engine,service,scheduler,world,tasks}.py`,
  `apps/behaviour/management/commands/simulate.py`, `api/views/behaviour.py`,
  `apps/orchestration/migrations/0003_f3_run_decision.py`, `tests/test_behaviour.py`

## Kontekst

Canon §18 definiše F3 kao „Behaviour + World + Scheduler". Canon zaključava
stanje (§4.2, 18 polja), deterministički reducer (§4.3), beat od 30 s sa
lookahead-om od 90 s (§11.1), prioritete buđenja (§11.2) i queue-ove (§11.3).
Dokument Faze 8 daje mehaniku: rutine, budžet pažnje, cooldown, World Engine,
relevantnost, due resolver, golden day. Ovaj ADR beleži šta je od toga
urađeno, kako, i šta je svesno ostavljeno za kasnije.

## Odluke

### 1. Tri sloja: čista odluka, čist reducer, baza

- `reducer.reduce(state, event, ctx)` — čista funkcija, pet pravila
  (`day.started`, `time.elapsed`, `activity.completed`, `window.closed`,
  `world.event.relevant`). Posle svake promene vrednosti se seku na opseg.
  Property test: 2000 nasumičnih pravila, nijedno polje van opsega.
- `engine.decide(snapshot)` — čista funkcija: prima stanje, rutine, vreme,
  seed; vraća odluku (ACT / SKIP / DEFER), razlog, niz pravila i sledeće buđenje.
- `service.wake()` — jedina funkcija koja piše stanje. Sve u jednoj transakciji.

Posledica: engine se testira bez baze, a 7 simuliranih dana traje 2 sekunde.

### 2. Vreme i slučajnost se nikad ne uzimaju „iz vazduha"

- Svaka funkcija prima `now`. Simulacija ima svoj sat (`SimClock`).
- Nema `random`. „Kockica" rutine je SHA-256 od (seed, persona, datum, prozor).
  Isti seed → ista priča; dve persone sa istom rutinom ne rade isto u isti minut.
- Seed: `BEHAVIOUR_SEED` ako je postavljen (simulacija), inače datum. Seed se
  upisuje u svaki run.
- Lokalno vreme postoji samo u `routines.py`; DST rešava `zoneinfo`.
  Testirano za Europe/Belgrade, Europe/Rome i UTC, oba prelaza.

### 3. Redosled provera pri buđenju (prvo „ne" odlučuje)

1. Persona pauzirana, suspendovana, degradirana → SKIP `PERSONA_PAUSED`.
2. Novi lokalni dan → `day.started` (oporavak preko noći, budžet se puni).
   Inače `time.elapsed` od poslednje promene.
3. Relevantan svetski događaj: ako persona radi (`work`/`post`) ili nema snage
   ili pažnje → DEFER `EVENT_DEFERRED`, inače ACT `read`.
4. Van prozora → DEFER `NO_WINDOW`. Prozor već odlučen danas → SKIP.
5. `rest` prozor → uvek SKIP `REST_WINDOW` (prozor bez aktivnosti, §25 u 21:05).
6. Kockica ≥ verovatnoća prozora → SKIP `ROUTINE_NOT_SELECTED`. Operator je preskače.
7. Energija < 0.25 ili pažnja < cena → SKIP `LOW_ENERGY_OR_BUDGET`. Operator je NE preskače.
8. Kognitivno opterećenje > 0.9 ili stres > 0.85 → SKIP `OVERLOADED`.
9. Ista aktivnost u cooldown-u → DEFER `COOLDOWN_ACTIVE` (buđenje na kraj cooldown-a).
10. Inače ACT. U F3 aktivnost je interna i odmah „završena": reducer primenjuje efekat.

Troškovi pažnje i cooldown-i su u `common/enums.py` (Faza 8 §8).

### 4. Lease = zaključan red stanja

`wake()` radi `SELECT … FOR UPDATE` nad `BehaviourState`. Dva workera ne
mogu istovremeno da računaju istu personu; ako worker padne, transakcija se
poništi i brava nestaje sama. Nema posebnih kolona `lease_owner`/`lease_expires_at`
iz §20, jer u F3 buđenje traje milisekunde. Kad planer dobije LLM (poziv od
nekoliko sekundi), brava se ne sme držati tokom poziva — tada se uvodi pravi
lease sa isticanjem (novi ADR).

Uz bravu, upis stanja i dalje ide `WHERE state_version = očekivana` (Canon §11.1).

### 5. Idempotentnost buđenja

`AgentRun.wake_key` je UNIQUE. Scheduler šalje `sched|<persona>|<due_at>`,
World Engine `world|<persona>|<event>`. Dvostruko isporučena poruka vraća
postojeći run. Test: 6 paralelnih buđenja sa istim ključem → 1 run.

### 6. Scheduler

- `behaviour.scan_due` na 30 s (beat), queue `persona.scheduled`.
- Upit iz Canon §11.1: `next_wake_at <= now + 90 s`, `ORDER BY wake_priority DESC,
  next_wake_at`, `LIMIT 500`, `FOR UPDATE SKIP LOCKED`.
- Izabranima se `next_wake_at` odmah pomera za 5 minuta („uzeto"). Ako se
  poruka izgubi, persona se vraća u izbor posle 5 minuta — izvor istine je
  PostgreSQL, ne Redis.
- `behaviour.wake` se zakazuje sa `eta = due_at`, jer scan gleda 90 s unapred.
- Scheduler budi samo **ACTIVE** persone. READY (P-00001) se budi samo ručno
  (`/wake`, `/behaviour/tick`, `simulate`). Aktivacija je zasebna radnja.
- Test: 200 due persona, 4 paralelna scana → nijedna izabrana dvaput.

### 7. World Engine — tri od sedam signala

Relevantnost iz §12 ima sedam signala. U F3 postoje tri: preklapanje tema
(tagovi persone kategorije `niche` sa težinom), geografija (region iz
`primary_locale`) i svežina. Ostali (cilj, odnos, novina iz memorije, jačina
interesovanja) nemaju izvor pre F4 i Social Graph-a. Da pragovi 0.28 / 0.52
ostanu smisleni, zbir se deli zbirom težina signala koji postoje. Kad signal
stigne, dodaje se i imenilac raste.

Dedup po `dedupe_key` (UNIQUE). Jedan događaj budi najviše 50 persona
(burst cap, §21); ostali dobijaju `store_only`.

### 8. API

- `POST /personas/{id}/wake` → 202 + `run_id` (operatorski zadatak, prioritet 100).
  U F3 se izvršava odmah; ugovor ostaje isti kad postane asinhron.
- `POST /personas/{id}/behaviour/tick` → buđenje kakvo bi napravio scheduler.
- `GET /ops/personas/{id}/timeline` → sva buđenja, filtrabilno po odluci.
  SKIP i DEFER su vidljivi isto kao ACT (§30).
- Budi: `operator`, `persona_manager`, `system_admin`. Oba POST-a traže `Idempotency-Key`.

### 9. Šema

`AgentRun` dobija `wake_key` (UNIQUE), `decision` i `reason_code`, plus indeks
`(persona, decision, started_at)`. Odluka je kolona, ne samo JSON, da bi
`wakeups_noop_ratio` bio jedan upit. Stanje dana (brojači, poslednja aktivnost,
odlučeni prozori, dnevni budžet) živi u `BehaviourState.state_ext`.

## Šta F3 namerno ne radi

- **Ciljevi i goal utility (§13)** — nema modela; dolazi uz F4/F5.
- **LLM rafinisanje kandidata (§14 korak 5)** — čeka LLM gateway.
- **Fairness preko jedne persone (§21)** — postoji jedan run po personi u isto
  vreme i burst cap; weighted fair queue i priority aging čekaju 20+ persona.
- **Metrike i dashboard (§27)** — podaci postoje u `AgentRun`; prikaz je F7.
- **Spoljne akcije** — nijedna. `post` je nacrt. `Action` se u F3 ne kreira nikada
  (test to proverava). `GLOBAL_EXTERNAL_ACTIONS_ENABLED` ostaje `false`.
- **Temporal** — Canon §11.4: odluka odložena do prelaza 50 → 75 persona.

## Posledice

- Nova migracija `orchestration 0003`. Novi beat task (30 s).
- Seed P-00001 dobija tri niše: `ai` 0.9, `b2b` 0.9, `sales` 0.7.
- `simulate` podrazumevano poništava sve (`--commit` čuva), jer simulirani
  dani leže u budućnosti i ne smeju da ostanu u stanju prave persone.
- 198 testova (F3 dodaje 32).
