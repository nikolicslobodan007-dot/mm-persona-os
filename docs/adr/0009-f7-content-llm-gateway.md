# ADR-0009 — F7: Sadržaj, planer objava, LLM Gateway

- **Status:** prihvaćeno
- **Datum:** 21.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §7.1, §9.4, §13, §15.2–15.3, §16.3, §17 · Memory v0.1 §7.2
- **Kod:** `apps/llm_gateway/{gateway,local}.py`, `apps/content/{service,planner,consumers,tasks}.py`,
  `apps/channels/management/commands/pilot_setup.py`, `api/views/content.py`,
  migracija `content 0004`, `tests/test_content.py`

## Kontekst

Posle F6 ceo put od odluke do adaptera postoji, ali ga niko ne pokreće osim
operatora. F7 zatvara krug: prozor „post” u rutini persone pravi nacrt, nacrt
postaje predlog objave, čovek odobrava, kapija pušta, adapter izvršava. Sve se
dešava u probnom režimu, a u SIMULATION samo na sandbox.

## Odluke

### 1. Nacrt je unutrašnji, objava je spoljna

- `content.draft()` ne ide kroz policy i nema spoljni efekat. Nastaje
  `ContentItem` (DRAFT), vezan za buđenje (`run`).
- `content.submit()` je jedini put do objave: `propose("channel.post.create")` →
  policy → A2 odobrenje (uvek, ADR-0007) → kapija → adapter.
- Sadržaj **ne menja status sam**. Status prati akciju preko potrošača eventa
  (`approval.resolved`, `action.queued/succeeded/failed/blocked`). Potrošač je
  idempotentan, jer je isporuka at-least-once.

| Akcija | Sadržaj | Objava |
|---|---|---|
| APPROVAL_PENDING | IN_REVIEW | SCHEDULED |
| QUEUED / RUNNING / RETRY_WAIT | APPROVED (ili SCHEDULED sa vremenom) | SCHEDULED |
| SUCCEEDED | PUBLISHED | PUBLISHED, `provider_payload.dry_run` |
| BLOCKED / FAILED / CANCELLED / EXPIRED | REJECTED (ako je čovek odbio) ili FAILED | FAILED |

`APPROVED_WITH_CHANGES` prepisuje tekst sadržaja iz akcije, povećava `version` i
računa novi hash. Odobren je izmenjeni tekst, pa u bazi ostaje on.

### 2. Nacrt prolazi iste zabrane kao objava

- Tekst iz modela ili od operatora proverava se sa `guards.prohibitions`. Pogodak
  znači REJECTED `HARD_PROHIBITION:<id>`, a takav nacrt ne može do `submit`.
- **Ponavljanje (Canon §16.3):** nacrt ≥ 80% sličan nekom nacrtu iste persone iz
  poslednjih 30 dana znači REJECTED `REPETITION`.
- **AI oznaka:** kad je `disclosure_mode = ALWAYS_VISIBLE`, tekst se završava sa
  „— Ime · AI persona”, a `disclosure_included = true`.
  To je obaveza iz EU AI akta, čl. 50 (Aneks A §4.1), a ne ukras.

### 3. Planer: prozor „post” → nacrt → predlog

- Buđenje sa ishodom ACT/POST registruje `schedule_draft(run)` **posle commit-a**.
  Nacrt može da pozove model, a to ne sme da se desi dok se drži brava stanja persone.
- U produkciji nacrt pravi Celery (`persona.scheduled`), a u dev-u se pravi odmah.
- Greška u nacrtu nikad ne obara buđenje.
- **Tema:** prva tema svetskog događaja koji je probudio personu. Ako takvog
  događaja nema, uzima se rotacija interesovanja persone po danu.
- **Kanal:** nalog sa uključenim `content.publish_approved` i poverenjem ≥ L1.
  U SIMULATION i SHADOW dolazi u obzir **samo SANDBOX**.
  Bez takvog naloga ostaje samo nacrt, jer predlog koji će sigurno biti
  odbijen samo pravi šum u redu odobrenja.
- Planer je idempotentan po `run`: jedno buđenje daje najviše jedan nacrt.
- Simulacija (`simulate` bez `--commit`) poništava transakciju, pa ne pravi nacrte.

### 4. Vreme objave je ograničeno važenjem odobrenja

`scheduled_for` mora da padne u narednih 120 minuta, koliko važi A2 odobrenje
(Canon §15.2). Kapija odbija izvršenje posle isteka odobrenja. Kalendar na više
dana traži ponovno odobrenje pred objavu, pa je odložen.

### 5. LLM Gateway: lokalni šablon uvek poslednji u lancu

`gateway.generate(purpose, …)` bira `LLMRoute` po svrsi i prioritetu, a pad
jedne rute vodi na sledeću. **Na kraju lanca je uvek `local/template-v1`**:
deterministički sastavljač iz šablona, bez mreže i bez troška.

- Sistem radi bez ijednog API ključa.
- Simulacija i testovi daju isti tekst za isti ulaz.
- Ceo tok može da se proveri pre izbora i plaćanja modela.

Lokalni šablon **nije model** i ne pretvara se da jeste. Tekst je jednostavan i
malo varira, pa će ponovljena tema posle nekoliko dana biti odbijena kao
`REPETITION`. To je ispravno ponašanje: kvalitet i raznovrsnost dolaze tek sa
pravim modelom.

Spoljni model se poziva samo ako važi sve troje:

1. `LLM_EXTERNAL_ENABLED=true` (podrazumevano je false);
2. ruta ima `data_training_allowed=True`, tj. provajder izričito **ne** trenira na
   našim podacima, jer prompt nosi memoriju persone;
3. postoji tajna preko `LLM_CREDENTIALS[provider]` (`env:`/`file:`), nikad u bazi.

Podržani su Anthropic Messages API i OpenAI-kompatibilni `/chat/completions`
(uz `LLM_BASE_URLS`). Model nije izabran ovim ADR-om. Ruta se dodaje u bazu kad
se model izabere merenjem, kao i embedding model (Canon §21).

**U bazi ostaju samo hash-ovi** prompta i odgovora (`PromptRecord`), tokeni
(`LLMUsage`) i trošak (`CostLedger`, zaokružen naviše na cent). Neuspeo poziv
ostavlja `PromptRecord` sa `error_code`, pa se vidi zašto je izabrana sledeća ruta.

### 6. Nacrt koji traži operator i dalje pripada buđenju

`POST /content/items` bez `run` pravi `AgentRun` sa `OPERATOR_TASK`. Canon §7.1
vezuje rad persone za buđenje, a `context.built` traži `run_id`. Tako i ručni
nacrt ima isti trag kao automatski: kontekst, prompt i trošak su vezani za run.

### 7. Pilot priprema je odluka čoveka

`pilot_setup --persona P-00001 --actor user:<ime>` radi dve stvari:

- na SANDBOX nalogu persone uključuje `content.publish_approved`;
- podiže poverenje za taj capability na L1, uz razlog u audit-u.

`--actor` mora biti čovek. Komanda ne dira stvarne kanale ni globalni prekidač.

### 8. API

Kanonske putanje (Canon §8.2):

- `POST /content/items`
- `POST /content/items/{id}/schedule`

Uz njih idu i `GET /content/items` i `GET /content/items/{id}`. Stavka u
`GET /approvals` sada nosi i `channel` (tip i handle), da odobravalac vidi gde
objava ide.

## Šta F7 namerno ne radi

- **Izbor pravog modela.** Ide merenjem na srpskom, posle pilota lokalnog toka.
- **Kalendar duži od važenja odobrenja** (ponovno odobrenje pred objavu).
- **Slike uz objavu** (Instagram ih traži). `visuals` i generisanje slika su posle pilota.
- **Odgovori na komentare i dolaznu poštu** (`reply` svrha postoji u gateway-u, tok ne).
- **Web UI za odobravanje.** Za sada `GET /approvals` i `POST /approvals/{id}/decision`.

## Posledice

- Migracija `content 0004`: `run` i `status_reason` na `ContentItem`.
- Potrošač `content.publication_sync` i task `content.draft_for_run` (`persona.scheduled`).
- Posle `pilot_setup` svako buđenje sa prozorom „post” stavlja nacrt u red za
  odobravanje. Neodobren nacrt ističe za 2 h (A2 → EXPIRED) i sadržaj prelazi u FAILED.
- 349 testova (F7 dodaje 23).
