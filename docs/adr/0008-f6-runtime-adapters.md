# ADR-0008 — F6: Runtime, adapteri, reconcile, lista odjava

- **Status:** prihvaćeno
- **Datum:** 21.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §6.2, §9.6, §12, §21 · Aneks A §2, §5, §6
- **Kod:** `apps/runtime/{config,transport,control,breaker,executor,tasks}.py`,
  `apps/runtime/adapters/`, `apps/channels/suppression.py`, `api/views/runtime.py`,
  `channels/platforms.yaml`, migracije `channels 0003`, `runtime 0002`, `tests/test_runtime.py`

## Kontekst

F5 je napravio kapiju (`gateway.authorize`) i odluku da je do GO svaki izvršni
ugovor `dry_run`. F6 pravi ono što stoji iza kapije: red, izvršioce, adaptere
po kanalu, retry, reconcile i circuit breaker. Pravilo iz Canon §12.1 je
ostalo netaknuto: **prvo zvanični API, browser samo gde uslovi to dozvoljavaju,
inače `CAPABILITY_UNAVAILABLE`**.

## Provera uslova platformi (Canon §21)

Aneks A je proveren 15.09.2026. Pre F6 (21.09.) ponovo su pregledani cenovnik
X API-ja, verzije LinkedIn Community Management API-ja i Instagram Content
Publishing dokumentacija. Nije nađena promena koja menja matricu. LinkedIn
verzija je podignuta na `202608`, jer je `202508` istekla 17.08.2026. Matrica je
u `channels/platforms.yaml` (`verified_on: 2026-09-21`, `reverify_by: 2026-12-15`).
**Pre GO odluke za svaki kanal proverava se ponovo.**

## Odluke

### 1. Nijedna društvena mreža nema browser put

| Kanal | Objava | Odgovor na komentar | Moderacija | Čitanje javnog |
|---|---|---|---|---|
| Facebook (Page) | API | API | API (skrivanje) | nedostupno |
| Instagram (professional) | API, traži sliku/video | API | API (skrivanje) | nedostupno u F6 |
| LinkedIn (Page + imenovani admin) | API | API, 1/min | API (brisanje) | nedostupno |
| X | API, trošak | API, trošak | nedostupno | API, trošak |
| Sandbox | interno | interno | interno | interno |
| Web | — | — | — | `browser.page.read` |

Lajk tuđe objave, follow, prvi DM i komentar na tuđem sadržaju **nemaju
ActionType**. Ne postoji sankcionisan put (Aneks A §1 t.3), a browser
automatizacija društvenih mreža bila bi upravo ono što Canon §12.1 isključuje.
Kanal bez puta vraća `CAPABILITY_UNAVAILABLE` / `UNSUPPORTED`. Akcija prelazi u
CANCELLED, ne u FAILED, jer je to očekivan ishod, a ne greška.

### 2. Transport je jedino mesto gde bajt izlazi — i ima drugu bravu

Adapter samo sastavlja `Request`, a šalje ga transport.

- `DryRunTransport` beleži šta **bi** bilo poslato. Taj zapis je u
  `ActionAttempt.payload.requests` i vidi se u `GET /actions/{id}`, pa operator
  pre GO vidi tačan zahtev: URL, telo, zaglavlja i verziju API-ja.
- `LiveTransport` **ponovo** proverava `GLOBAL_EXTERNAL_ACTIONS_ENABLED`. Ako
  mu neko greškom preda ugovor bez `dry_run`, ne šalje ništa
  (`EXTERNAL_ACTIONS_DISABLED`).
- Tajna se čita tek u `LiveTransport`, iz `credential_ref` (`env:IME` ili
  `file:/putanja`). U evidenciji stoji `Bearer ‹credential_ref›`, nikad vrednost.
  `vault:` još nije podržan i daje `NEEDS_AUTH`.

### 3. Tok izvršenja

`ALLOW → enqueue → WorkerJob`. Posao nastaje samo na ALLOW. Interne akcije
(`content.draft`, `memory.consolidate`) ne ulaze u red. `execute_job` ide ovim redom:

1. claim (SKIP LOCKED), zatim breaker, pa sesija. Po personi je dozvoljeno 1 write i
   3 read. Za pisanje to čuva jedinstveni indeks u bazi, za čitanje brojanje pod
   bravom. Zauzeto znači novi pokušaj za 10 s, bez trošenja pokušaja.
2. `gateway.authorize()`. Istekla odluka dobija novu evaluaciju, a ne izvršenje.
3. Akcija prelazi u RUNNING, upisuje se `ActionAttempt` i emituje `runtime.execution.started`.
4. Adapter radi van transakcije. Pre **svakog** zahteva poziva se `CancelToken.check()`:
   kill-switch, rok, heartbeat na 20 s koji produžava lease na 90 s, i gornja granica od 45 s.
5. Ishod se preslikava po Canon §3.9, uz event, trošak (samo uživo) i breaker.

### 4. Retry i reconcile (Canon §12.3–12.4)

- Čitanje ima najviše 3 pokušaja (backoff 2 s, 8 s), a pisanje 2 (backoff 30 s).
  Uvek važi `max(backoff, Retry-After)`.
- `RETRYABLE_ERROR` za pisanje nastaje **samo** kad se zna da efekta nema: 429,
  greška pre slanja ili prekid pre prvog zahteva koji menja stanje.
- 5xx, timeout ili prekid **posle** zahteva koji menja stanje daju `UNKNOWN_EFFECT`.
  Akcija tada ostaje RUNNING i nastaje `ReconcileTask`. Retry je tu zabranjen.
- Reconcile (beat 60 s) pita adapter `verify()`:
  - `EFFECT_PRESENT`: akcija prelazi u SUCCEEDED;
  - `NO_EFFECT`: novi pokušaj ako ih ima, inače FAILED;
  - neodlučno 5 puta: FAILED `RECONCILE_UNRESOLVED` i SEV2 incident, pa proveru radi čovek.
- Mejl nema način da se proveri, pa sumnjiva pošta uvek ide čoveku.
- Izgubljen worker (lease istekao, beat 30 s): čitanje se ponavlja kao `ABORTED_SAFE`,
  a pisanje ide u reconcile kao `UNKNOWN_EFFECT`.

### 5. Kill-switch u letu

F5 blokira sve **otvorene** akcije u opsegu. Akciju u RUNNING zaustavlja sam
worker, na sledećoj proveri pre zahteva:

- stop pre prvog zahteva koji menja stanje daje `ABORTED_SAFE`, akcija prelazi u
  BLOCKED `KILL_SWITCH`, a sesija u ABORTED;
- stop između dva zahteva (npr. Instagram kontejner je napravljen, a objava nije
  poslata) daje `UNKNOWN_EFFECT` i ide u reconcile.

Zahtev koji je već otišao ne može se povući. Zato je granica zaustavljanja
između zahteva, a ne usred zahteva. Aktivacija beleži broj akcija u letu
(`in_flight`), a worker beleži `stop_latency_ms` od aktivacije do svog zaustavljanja.

### 6. Circuit breaker (Canon §12.5)

Breaker je po paru (adapter, nalog) i čuva se u bazi, pa važi za sve worker-e i
preživljava restart.

- Pet grešaka kanala u 60 s (429, 5xx, mreža, timeout, `UNKNOWN_EFFECT`) otvara ga
  (OPEN) i otvara SEV3 incident.
- Posle 120 s prelazi u HALF_OPEN i pušta najviše 3 probe.
- Uspeh ga zatvara, a greška ga ponovo otvara.
- Naša odbijanja (tempo, plafon, repetition guard) se ne broje.

### 7. Pošta (Canon §12.8, Aneks A §6)

Provere pre slanja, koje važe i u dry-run-u:

- lista odjava;
- `mail.send` nikada sa `PRIMARY_COMPANY_DOMAINS` ni sa njihovih poddomena;
- najviše 3 aktivna mejlboksa po `sending_domain`;
- dnevni plafon mejlboksa, sa zagrevanjem 5 → plafon za 21 dan;
- jedna poruka ide jednom primaocu.

Poruka:

- From je poravnat sa domenom slanja (DMARC), a Reply-To je javna adresa persone;
- nosi `List-Unsubscribe` i `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
  (RFC 8058), plus link za odjavu i ime pošiljaoca u podnožju.

`mail.reply` (odgovor na dolaznu poštu) ne proverava listu odjava. Primalac je
sam pisao, a odgovor na upit nije komercijalna poruka.

### 8. Centralna lista odjava

`SuppressionEntry` čuva **samo sha256 normalizovane adrese** (ili domena).
Lista zna da je adresa odjavljena, a ne zna koja je, pa ne postaje baza kontakata.

Link za odjavu nosi potpisan hash (`django.core.signing`). GET prikazuje dugme,
a POST odjavljuje. Skeneri linkova u mejl klijentima rade GET i zato ne smeju da
odjave nikoga. Odjava važi za sve persone i sve mejlbokseve i ne briše se.

### 9. Javni web (Aneks A §5)

- Istinit User-Agent sa kontaktom, iz `capabilities.yaml`.
- `robots.txt` se poštuje i kešira 24 h (401/403 znači sve zabranjeno, po RFC 9309).
  `Crawl-delay` se poštuje.
- Najviše 1 zahtev u sekundi po hostu, preko zajedničkog keša (Redis u produkciji).
- Uslovni GET (ETag / Last-Modified).
- Nikad prijava, nalog ni „prihvatam".
- Forme (`browser.form.submit`) idu **samo** na domene iz
  `BrowserProfile.allowed_domains`, a polje koje liči na lozinku ili token se odbija.
- CAPTCHA ili izazov daje `NEEDS_HUMAN`. Sistem ga ne rešava.

### 10. X: repetition guard i trošak

Objava ili odgovor koji je ≥ 80% sličan (Jaccard na 3-gramima reči, bez
dijakritika i linkova) bilo kojoj X akciji u poslednjih 30 dana, sa **bilo kog**
naloga, daje DENY `REPETITION_GUARD`. To je uslov pristupa po X developer
politici, a ne stil.

Trošak (0,015 $, odnosno 0,20 $ sa linkom) upisuje se u `CostLedger` samo uživo,
zaokružen naviše na cent. U dry-run-u se samo procenjuje (`estimated_cost_usd`).

### 11. `run_id` van buđenja

`runtime.execution.started/finished` i `action.succeeded/failed` dodati su u
`RUN_ID_OPTIONAL`. Obrazloženje je isto kao u ADR-0007 §9: izvršenje nasleđuje
run akcije, a operatorska akcija ga nema.

### 12. API

Kanonske putanje iz Canon §8.2:

- `GET /channels/accounts`
- `GET /channels/accounts/{id}/capabilities` (presek platforme, naloga i policy-ja)
- `GET /ops/overview`

`GET /actions/{id}` sada vraća i `result`, a u pokušajima `requests`, `dry_run` i
`estimated_cost_usd`.

**Nove putanje (dopuna Canon §8.2 ovim ADR-om):**

- `POST /mail/suppressions` — ručna odjava adrese ili domena;
- `GET|POST /mail/unsubscribe` — javna, bez prijave, izuzeta iz obaveznih
  header-a (Canon §8.5), jer dolazi iz mejl klijenta.

## Šta F6 namerno ne radi

- **Uživo slanje.** Prekidač ostaje `false`. Živi putevi su testirani lažnim
  transportom, a ne pravim nalozima.
- **Playwright u image-u.** Postoji kao `pip install -e ".[browser]"`. Ulazi u
  image tek kada zatreba `render: true` ili forma.
- **Web Bot Auth / Signed Agents** (Aneks A §5.3). Posle pilota, uz ključ za potpis.
- **Dolazna pošta i webhook-ovi kanala** (`/webhooks/mail/{provider}`,
  `/webhooks/channel/{provider}`), zajedno sa izborom mail provajdera.
- **Automatska obrada prijava i bounce-ova.** Upis je spreman
  (`SuppressionReason.COMPLAINT/HARD_BOUNCE`), a izvor su webhook-ovi.
- **`vault:` credential_ref.** Za pilot su dovoljni `env:` i `file:`.

## Posledice

- Migracije `channels 0003` (`SuppressionEntry`) i `runtime 0002` (`CircuitBreaker`).
- Tri nova beat taska: `runtime.dispatch_due` (15 s, control), `runtime.reap_leases`
  (30 s, maintenance) i `runtime.reconcile` (60 s, maintenance).
- `worker_browser` (queue `browser`) mora da radi da bi se čitanje weba izvršavalo.
- Produkcija koristi Redis keš (baza 1) za tempo po hostu, robots.txt i ETag.
- 326 testova (F6 dodaje 48).
