# ADR-0007 — F5: Policy / Approval / Trust / Kill-switch / Gateway

- **Status:** prihvaćeno
- **Datum:** 21.09.2026.
- **Canon verzija:** 1.1
- **Izvor:** MM Persona OS — Policy / Approval / Trust Engine v0.1 (Faza 10)
- **Kod:** `apps/policy/{config,guards,engine,service,gateway,tasks}.py`, `api/views/policy.py`,
  `apps/policy/migrations/0002_f5_policy_decision.py`, `tests/test_policy.py`

## Kontekst

> Planner predlaže. Policy odlučuje. Approval potvrđuje. Action Gateway jedini izvršava. (Canon §9.1)

Canon zaključava efekte (§3.5), klase rizika (§3.6), izvedenu zonu (§3.7),
formulu rizika (§9.2), pilot limite (§9.3), tvrde zabrane (§9.4), trust matricu
(§9.5), kill-switch hijerarhiju (§9.6), klase odobrenja i TTL (§15.2) i vezivanje
odobrenja za hash (§15.3). F1 je napravio tabele i CHECK ograničenje „nema QUEUED
bez odluke". F5 pravi mehanizam koji jedini sme da akciju dovede do QUEUED, i
kapiju kroz koju F6 adapteri moraju da prođu.

## Odluke

### 1. Evaluator je čista funkcija

`engine.evaluate(ctx)` ne dira bazu, sat ni slučajnost. Isti kontekst daje istu
odluku, pa se svaka odluka može ponoviti i objasniti. Redosled provera:

1. kill-switch u opsegu → DENY `KILL_SWITCH_ACTIVE`
2. nepoznat `ActionType` → DENY `UNKNOWN_ACTION_TYPE` (default deny)
3. tvrde zabrane (§9.4) → DENY `HARD_PROHIBITION`
4. persona nije READY/ACTIVE → DENY
5. capability: trust ≥ `min_trust_level`, aktivan grant (za L1+), kanal obavezan
   za `channel.*`/`mail.*`, nalog aktivan, capability uključen na nalogu, AI oznaka
   postavljena gde je obavezna, četiri parametra za `web.read_public` → DENY
6. dnevni limiti (§9.3) — **ukupnih 40 prvo**, pa dimenzija → THROTTLE
7. rizik: CRITICAL → DENY; HIGH → odobrenje; MEDIUM uz trust < L2 → odobrenje
8. pravila iz baze (`PolicyRule`) i `requires_approval_class` capability-ja
9. važeće odobrenje **istog hash-a** ispunjava zahtev za odobrenjem

Prednost: DENY > THROTTLE > REQUIRE_APPROVAL > ALLOW. Svi razlozi se čuvaju
(`reason_codes`), prvi je odlučujući. Od dve klase odobrenja bira se strožija
(A4 > A3 > A1 > A2).

### 2. Rizik tačno po Canon §9.2

Osam celih komponenti iz `policy/risk_weights.yaml`, zbir minus `trust_credit`,
sečeno na 0–100. Svaka komponenta se čuva u odluci (`risk_components`).
`risk_delta` iz seed pravila **nije** deo formule i ne ulazi u skor — pravilo
određuje efekat, formula određuje rizik.

Izvedeni signali: publika po tipu akcije (objava = public, mail = named_individual,
čitanje = internal); novina iz istorije persone (0 na kanalu = first_on_channel,
≤4 new, 5–20 familiar, >20 routine); obim iz udela dnevnog plafona; sadržaj iz
teksta (regulisane teme, pominjanje trećih lica, brojke) ili iz `content_class`.

### 3. Tvrde zabrane — ne isključuju se

`guards.prohibitions()` prepoznaje sedam zabrana iz `capabilities.yaml` kroz
zastavice u payload-u i obrasce u tekstu (srpski i engleski, bez dijakritika).
Konzervativno: lažna uzbuna ide čoveku, propust ide u javnost. Pogodak:

- DENY + `policy.incident.opened` SEV1,
- trust na **L0** za capability-je akcije, grant opozvan, `auto_downgrade_count` +1,
- persona **SUSPENDED** (dalje akcije: DENY `PERSONA_NOT_OPERATIONAL`).

Isto važi i kad zabranu uvede **odobravalac** kroz `APPROVED_WITH_CHANGES`: izmenjen
sadržaj prolazi kroz iste provere.

### 4. Tok akcije

`service.propose()` → `Action` (PROPOSED, `idempotency_key` po Canon §6.3,
`content_hash`) → odluka → prelaz:

| Efekat | Status akcije | Event |
|---|---|---|
| ALLOW | QUEUED | `action.queued` |
| REQUIRE_APPROVAL | APPROVAL_PENDING + `ApprovalRequest` | `approval.requested` |
| THROTTLE | BLOCKED (`THROTTLED`) | `action.blocked` |
| DENY | BLOCKED (`DENIED_BY_POLICY`) | `action.blocked` |

Uvek i `action.proposed` + `policy.decision.created`. Isti predlog dvaput →
ista akcija (`created=false`).

**Kvota je atomična:** predlog zaključava red persone, pa paralelni predlozi ne
mogu zajedno da probiju plafon (test: 36 potrošeno, 8 paralelno → tačno 4 prolaze).

**Fail-closed** (Canon §12.4): izuzetak ili evaluacija duža od
`POLICY_EVAL_TIMEOUT_SECONDS` → DENY sa `fail_closed=true`, rizik 100.

### 5. Odobrenja (§8.3, §15.2–15.3)

- Jedan endpoint `/approvals/{id}/decision`: APPROVED, APPROVED_WITH_CHANGES, REJECTED.
- Odlučuje samo nosilac dozvole `policy.decide_approval` (operator, persona_manager,
  trust_safety — `bootstrap_roles`). `decided_by` je uvek prijavljeni korisnik.
- **Odobrava se sadržaj:** `payload_hash` mora biti jednak `content_hash`.
  APPROVED_WITH_CHANGES menja payload, računa novi hash, vezuje odobrenje za njega
  i ponovo evaluira (sa tvrdim zabranama).
- Posle odobrenja uvek **nova evaluacija** (Policy v0.1 §17.3) — kill-switch ili
  pad poverenja u međuvremenu i dalje pobeđuju.
- Druga odluka o istom odobrenju → 409. Isteklo odobrenje se ne može odobriti.
- **Istek** (beat, 60 s): A1 → akcija CANCELLED (nacrt ostaje), A2 → EXPIRED,
  A3 → BLOCKED, A4 → BLOCKED + SEV2 incident.

### 6. Poverenje (§3.11, §9.5)

- Matrica `(persona, capability) → nivo` u `TrustState`; bez reda = L0.
- `trust/change` smeju `trust_safety` i `system_admin`; razlog je obavezan.
- **L3 i L4 se odbijaju** (rezervisani do ADR-a koji imenuje kanal).
- Nivo ≥ minimum capability-ja (L1+) → aktivan `CapabilityGrant`; pad ispod → grant opozvan.
- Prikaz jednog broja je **minimum** po capability-jima.
- `Persona.trust_level` se ne menja automatski — izvor istine je matrica.

### 7. Kill-switch (§9.6)

- GLOBAL / CHANNEL / PERSONA / CAPABILITY / ACCOUNT, jedan aktivan po (scope, target).
- Aktiviranje: sve otvorene akcije u opsegu (PROPOSED…RETRY_WAIT) → BLOCKED
  (`KILL_SWITCH`), njihova odobrenja → CANCELLED, meri se `stop_latency_ms`.
- Aktivira svaka uloga osim `viewer`; pušta samo `trust_safety`, `runtime_admin`,
  `system_admin`. Zaustaviti je lako, pustiti je namerno teže.
- Puštanje ne vraća blokirane akcije — posle stopa ide novi predlog.
- Proverava se dvaput: u evaluaciji i ponovo u gateway-u neposredno pre izvršenja.

### 8. Action Gateway

`gateway.authorize(action)` je jedini put do izvršnog ugovora (Canon §12.6). Ponovo
proverava: QUEUED + ALLOW + odluka nije istekla; hash sadržaja i ulaza isti kao pri
odluci; odobrenje važi i vezano je za isti hash; kill-switch; status persone; AI oznaku.
Odbijanje upisuje BLOCKED + `action.blocked` pa tek onda baca `GatewayRefused`.

**`dry_run`** je true kad god spoljni efekat ne sme da nastane: globalni
`GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`, persona van CONTROLLED_LIVE/LIVE, ili interna
akcija. Do GO odluke prekidač je isključen, pa je **svaki ugovor dry_run**.
F6 adapter koji dobije `dry_run=true` ne sme da dodirne spoljni sistem.

### 9. `run_id` van buđenja

Akciju sme da predloži i operator, van buđenja persone. Canon §7.1 traži `run_id` za
policy/orchestration evente „koji nastaju unutar buđenja", a §2 kaže da je za
operatorske zapise null. `action.proposed`, `policy.decision.created`,
`approval.requested/resolved`, `action.queued/blocked`, `trust.level.changed` i
`policy.incident.opened` dodati su u `RUN_ID_OPTIONAL`; šeme dozvoljavaju null.
Kad akcija ima run, emiter ga uvek prosleđuje. `persona.woken` i `plan.created`
ostaju sa obaveznim `run_id` (test u `test_canon.py` sada koristi `plan.created`).

### 10. API

`POST /actions/propose`, `POST /policy/evaluate` (sa `action_id` = nova odluka;
bez njega = proba bez upisa, `decision_id: null`), `POST /policy/evaluate/batch`
(do 50 proba), `GET /approvals`, `POST /approvals/{id}/decision`,
`POST /personas/{id}/trust/change`, `GET|POST /kill-switches`
(`operation: activate|clear`), `GET /policy/incidents`. Odgovor odluke je oblik
iz Canon §8.4 (`reason_codes`, `matched_rules`, `obligations`, `constraints`,
`policy_version`, `input_hash`, `expires_at`, izvedena `zone`).

## Usklađivanje sa Canon-om

Faza 10 u scenariju A daje ALLOW za objavu na L1. Canon §15.2 i `capabilities.yaml`
traže **A2 odobrenje za svaku javnu objavu** — Canon pobeđuje: objava je uvek
REQUIRE_APPROVAL dok se to ne promeni ADR-om.

## Šta F5 namerno ne radi

- **Centralna suppression lista** (Canon §12.8 t.6) — obaveza `CHECK_SUPPRESSION_LIST`
  se izdaje za `mail.send`, ali model i provera dolaze sa mail adapterom u F6 (zaseban ADR).
- **Zaustavljanje radnika u letu** — nema izvršilaca do F6; tada kill-switch dobija
  signal na `control` queue i merenje „< 30 s do poslednjeg radnika".
- **Automatski rast poverenja iz metrika** (Policy v0.1 §7.1) — samo ručno i samo pad automatski.
- **Limiti po nalogu/satu, po primaocu/danu, po kampanji** — posle pilota, kad postoje podaci.
- **Hash-lanac audita** — i dalje otvoreno.

## Posledice

- Migracija `policy 0002`: `policy_version`, `reason_codes`, `obligations`,
  `constraints`, `expires_at` na `PolicyDecision`.
- Novi beat task (60 s) na queue-u `approval`.
- `GLOBAL_EXTERNAL_ACTIONS_ENABLED` ostaje `false`; nijedna akcija nema spoljni efekat.
- 278 testova (F5 dodaje 43).
