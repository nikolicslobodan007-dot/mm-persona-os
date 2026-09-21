# ADR-0004 — F2: API, event bus i audit

- **Status:** prihvaćeno
- **Datum:** 21.09.2026.
- **Canon verzija:** 1.1
- **Izvor:** MM Persona OS — API & Event Contracts v0.1
- **Kod:** `api/`, `apps/observability/{bus,consumers,tasks}.py`,
  `apps/policy/management/commands/bootstrap_roles.py`,
  `contracts/openapi/persona-os-v1.yaml`, `tests/test_api.py`, `tests/test_openapi.py`

## Kontekst

Canon §18 definiše F2 kao „API + event bus + audit". Canon kaže *šta* mora
da važi (§7 envelope i katalog, §8 putanje, header-i, greške, paginacija,
§15 uloge, §16.5 tvrdi KPI), ali ne i *kako*. Ovaj ADR beleži izbore koji
nisu u Canon-u i šest mesta gde se Contracts v0.1 ne slaže sa Canon-om.

## Odluke

### 1. Event bus = transakcioni outbox u Postgres-u

`bus.emit()` upisuje event u `EventOutbox` **u istoj transakciji** kao i
promenu koju opisuje, i odbija da radi van `transaction.atomic()`. Posle
commit-a Celery (`observability.publish_outbox`, red `control`) isporučuje
event potrošačima; beat ponavlja krug na 30 s za slučaj da Redis nije
odgovorio. Nema Kafke, NATS-a ni Redis Streams-a.

- **Isporuka je at-least-once.** Svaki potrošač ima red u `EventDelivery`
  sa jedinstvenim `(consumer, event_id)`; drugi pokušaj istog eventa ne radi
  ništa. Test: isti event isporučen 10× → jedan efekat.
- **Pad potrošača** ostavlja red `PENDING` sa `last_error`; posle 10 pokušaja
  red postaje `DEAD` i čeka čoveka. Uspešni potrošači se ne ponavljaju.
- **Šema pre upisa.** Envelope se proverava protiv
  `schemas/events/<tip>/<verzija>.json` (Draft 2020-12). Event van kataloga
  ili sa pogrešnim payload-om ne ulazi u outbox (Canon §7.3).
- Zašto: jedna mašina, jedan tim, obim meren hiljadama eventa dnevno.
  Outbox u bazi koju već imamo daje atomičnost bez distribuirane transakcije.
  Prelaz na broker kasnije menja samo `publish_pending`, ne producere.

### 2. Idempotentnost u Postgres-u, ne u Redis-u

`@idempotent` upisuje `IdempotencyRecord (scope, key)` u istoj transakciji
kao efekat. Jedinstveni indeks je brava: paralelni isti zahtev čeka, pa
dobija sačuvan odgovor (sa `Idempotent-Replayed: true`, `ETag`, `Location`).
Isti ključ sa drugačijim telom → 409 `IDEMPOTENCY_CONFLICT`. Greška poništava
i zapis, pa ponovljen zahtev kreće ispočetka. TTL 24 h (Canon §6.3).
`scope` je principal, pa dva korisnika ne mogu da se sudare istim ključem.
Test: 8 paralelnih istih zahteva → jedna persona.

### 3. Prijava i uloge: Django grupe + tokeni, bez Keycloak-a

- Šest uloga iz Canon §15.1 su Django grupe istog imena
  (`bootstrap_roles`, idempotentno). `reviewer` nije uloga nego dozvola
  `policy.decide_approval`, data grupama iz `APPROVAL_DECIDERS`.
- Prijava je `TokenAuthentication`. Sesije i CSRF nisu uključeni za API —
  koriste ga servisi i skripte.
- Servisni nalozi su korisnici sa prefiksom `svc_`; oni smeju da deklarišu
  tuđeg pokretača u `X-Actor-ID` (npr. `persona:P-00001`). Čovek sme da
  deklariše samo sebe, inače 403 `FORBIDDEN`.
- Keycloak/OIDC ostaje opcija za F9 ako zatreba SSO. Zamenjuje se klasa
  prijave, ne provera uloga.

### 4. Nove tabele žive u `observability`

`EventOutbox`, `EventDelivery`, `IdempotencyRecord` su infrastruktura traga
i isporuke — isti vlasnik kao `AuditEvent` (Canon §1). `api/` nije Django
app nego deljeni paket bez modela.

### 5. Sprovođenje header-a (Canon §8.5)

- Upis (POST/PUT/PATCH/DELETE pod `/api/v1/`): `X-Request-ID`, `traceparent`
  i `X-Actor-ID` su obavezni, inače 400 pre nego što se išta dotakne.
- Čitanje: što nedostaje se generiše i vraća u `X-Request-ID`/`X-Trace-ID`.
- Neispravan header se odbija uvek, i na čitanju.
- `/api/v1/webhooks/` je izuzet — provajder ne zna naše header-e; zaštita je potpis.
- `/healthz` je van ugovora.

### 6. Audit

`api.audit.record()` piše `AuditEvent` sa `trace_id`, principalom,
`before_hash`/`after_hash` (SHA-256 kanonskog JSON-a) i `payload_hash`.
Ključevi koji liče na tajnu (`password`, `token`, `secret`…) se brišu pre
upisa. Svaki event iz bus-a dobija i audit red `event.<tip>` preko potrošača
`observability.audit`. Hash-lanac između redova je zaseban posao (otvoreno).

### 7. OpenAPI ugovor u repou

`contracts/openapi/persona-os-v1.yaml` se generiše iz koda
(drf-spectacular) i commit-uje. `tests/test_openapi.py` pada ako se kod i
fajl razlikuju — ugovor ne može tiho da zastari.

### 8. Šta F2 namerno ne radi

- `POST /actions/propose`, odobrenja i kill-switch preko API-ja → F5
  (predlog akcije bez policy engine-a iza sebe krši Canon §6.2).
- `wake`, `behaviour/tick` → F3, uz scheduler.
- Kreiranje persone ne emituje event: katalog (§7.2) nema `persona.*`.
  Trag je audit red `api.persona.created`.

## Sukobi Contracts v0.1 ↔ Canon v1.1 (Canon pobeđuje, §0)

| # | Contracts v0.1 | Canon v1.1 | U kodu |
|---|---|---|---|
| 1 | `correlation_id` u envelope-u i header-u | `trace_id` iz W3C `traceparent` | `trace_id` |
| 2 | `AUTH_REQUIRED` | `UNAUTHENTICATED` | `UNAUTHENTICATED` (401) |
| 3 | 503 za pad spoljnog provajdera | 502 `PROVIDER_UNAVAILABLE` | 502 |
| 4 | `/personas/{id}` (UUID) | `/personas/{public_id}` (P-00001) | `public_id` |
| 5 | `/approvals/{id}/approve` i `/reject` | jedna `/approvals/{id}/decision` | F5, po Canon-u |
| 6 | `disclosure_mode = EXPLICIT_AI` | ne postoji; `ALWAYS_VISIBLE`/`PROFILE_ONLY`/`ON_REQUEST` | Canon vrednosti |

## Posledice

- Nova zavisnost: `drf-spectacular`. Nove tabele: 3 (+ `authtoken_token`).
- Posle deploy-a: `migrate`, pa `bootstrap_roles`, pa ručno dodela uloge i token.
- CI sada diže pgvector Postgres i instalira `.[dev]`; ranije je padao na Django testovima.
- `pyproject.toml` dobio `[build-system]` i `packages = []`: bez toga je
  `pip install -e .` padao na flat-layout, a Dockerfile je tiho koristio
  rezervnu listu paketa bez drf-spectacular-a. Rezervna lista je uklonjena.
