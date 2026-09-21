# ADR-0006 — F4: Memory & Knowledge

- **Status:** prihvaćeno
- **Datum:** 21.09.2026.
- **Canon verzija:** 1.1
- **Izvor:** MM Persona OS — Memory & Knowledge Engine v0.1 (Faza 9)
- **Kod:** `apps/memory/{embeddings,writer,retrieval,context,lifecycle,golden,tasks}.py`,
  `apps/memory/management/commands/memory_eval.py`, `api/views/memory.py`,
  `apps/memory/migrations/0003_f4_memory_engine.py`, `tests/test_memory.py`

## Kontekst

Canon §10 zaključava imena i formule (salience, eligibility M, retrieval R,
decay sa λ po tipu, confidence po izvoru, provenance) i kaže da se embedding
model bira **posle F4 merenja** (§21). Dokument Faze 9 daje mehaniku:
writer, hibridni retrieval, Context Builder, konsolidaciju, protivrečnosti,
retention i privatnost. F1 je već napravio tabele; F4 ih oživljava.

## Odluke

### 1. Embedding: ruter + lokalni model + merenje, bez izbora provajdera

Canon §21 odlaže izbor modela. Zato F4 ne bira provajdera nego pravi uslove
za izbor:

- `embeddings.PROVIDERS` je ruter; model se bira sa `EMBEDDING_MODEL`.
- Jedini registrovani model je **`local-hash-v1`**: feature hashing reči i
  trigrama slova, sa svođenjem dijakritika (č→c, đ→dj). Nema mreže, nema
  troška, determinističan je, i prepoznaje isti koren kroz padeže.
  Nije pravi semantički model — to je donja granica.
- **`manage.py memory_eval`** meri hit@5, MRR i p95 na zlatnom skupu
  (24 memorije, 12 pitanja na srpskom, pitanja namerno u drugim padežima).
  `local-hash-v1`: **hit@5 1.00 · MRR 0.92 · p95 9 ms**.
- Test drži hit@5 ≥ 0.90 kao kapiju protiv regresije.

Kad se kandidat-model doda u ruter, isti `memory_eval` daje uporediv broj.
Promena modela = nova vrednost `model_key` u `memory_embedding` + `reindex`,
bez izmene postojećih vektora (Canon §10.5).

### 2. Writer (Memory v0.1 §5)

Redosled: tajne → provenance ↔ izvor → eligibility M → dedup → upis → izvor
→ vektor → tvrdnja → `memory.created`.

- **Tajne se odbijaju** (`SECRET_MATERIAL`): lozinka, ključ, token, privatni ključ.
  Memorija čuva samo `credential_ref`, nikad vrednost.
- **Provenance mora da odgovara izvoru** (`llm_inference` ne može biti `observed`).
- **Izvod o samoj personi se ne upisuje kao činjenica** (Canon §10.4).
- **Eligibility M** je formula iz Canon §10.2; `sensitivity_penalty = 0.30 · sensitivity`.
  Pragovi po tipu su u `MEMORY_ELIGIBILITY_MIN` (working 0, episodic 0.25, …).
  Ispod praga je normalan ishod `rejected`, ne greška.
- **Dedup:** isti `source_event_id` (UNIQUE po personi i tipu) vraća postojeći
  zapis; isti normalizovani sadržaj pojačava postojeći (novi izvor, +0.02 pouzdanosti).
- **Radna memorija** ističe posle 6 sati.

### 3. Protivrečnosti — bez izmišljenog pobednika (§10.1, §18.1)

Tvrdnja je (subjekat, predikat, vrednost). Ista tvrdnja sa drugom vrednošću:

- nova je eksplicitna potvrda čoveka **ili** ima pouzdanost ≥ staroj − 0.05
  → stara postaje SUPERSEDED (`superseded_by`, `valid_to`, veza `supersedes`);
- inače → protivrečnost ostaje **OTVORENA**, obe memorije aktivne, a kontekst
  ih označava „⚠ sporno" i oduzima 0.15 od skora;
- PINNED se nikad ne zamenjuje automatski;
- ista vrednost → pojačanje, ne duplikat.

Svaki slučaj pravi `MemoryContradiction` red i `memory.contradiction_detected`.

### 4. Retrieval (Canon §10.2, Memory v0.1 §6–7)

- Uvek u okviru jedne persone; samo ACTIVE i PINNED; istekla radna memorija ne ulazi.
- Kandidati: vektorski top 60 ∪ najnovijih 30 ∪ najvažnijih 30. Bez vektora
  (pad modela) → poslednjih 500, i pamćenje radi dalje (§6 fallback).
- Konačni rang je **R iz Canon §10.2**. Svaki rezultat nosi razlaganje skora.
- `task_relevance` = preklapanje korena reči (prvih 5 slova) upita i memorije.
  Postgres FTS nema srpski rečnik, pa je ovo zamena dok se ne izmeri potreba.
- `relationship` = 0 u F4 (nema Social Graph-a).
- Osetljivo (≥ 0.70) ulazi samo za svrhu `summarise`.
- Težine su iste za sve profile (Canon formula); profili menjaju top-k i budžet tokena.

### 5. Context Builder (§12)

Sekcije: `persona_core` (sa AI oznakom), `current_state`, `task_goal`,
`policy_constraints`, `retrieved_memory`. **Tvrdi plafon tokena** se nikad ne
prelazi; višak se odseca i beleži (`truncated`). Procena ⌈znakova/4⌉ dok ne stigne
tokenizer. Svaki paket je `MemoryContextPack` (ID-jevi, skorovi, hash) + `context.built`.
Izvod nosi oznaku „izvod, ne činjenica". Context Builder, ne retriever, beleži prisećanje.

### 6. Životni ciklus (§8–9, §14)

- **Dnevna konsolidacija** u 03h po lokalnom vremenu persone: epizode dana →
  jedan zapis „Dan YYYY-MM-DD" (odluke, aktivnosti, teme, naslovi). Originali se
  **arhiviraju**, ne brišu, i ostaju povezani vezom `derived`. Prekretnice
  (salience ≥ 0.8) ostaju aktivne. Sažetak je deterministički, ne LLM.
  Idempotentno (`consolidation:daily:<datum>`).
- **Bleđenje:** efektivna važnost < 0.05 → ARCHIVED. Osnovna `salience` se ne menja.
- **Istek radne memorije** svaki sat.
- **Brisanje** (`lifecycle.forget`) propagira: vektori, veze i reference izvora
  se uklanjaju, sadržaj se prepisuje, red ostaje kao DELETED zbog audita.
- Jedan beat task `memory.maintenance`, svaki sat, queue `memory`.

### 7. Veza sa F3

Buđenje sa ACT ostavlja epizodu (izvor = run). Odložena vest ostavlja epizodu
„zapažena, odložena". World Engine za `store_only` upisuje epizodu umesto da budi
personu. Sve prolazi kroz eligibility, pa sitnice ne ulaze.

### 8. API

- `POST /personas/{id}/memories` → 201 (`created`) ili 200 (`duplicate` /
  `reinforced` / `rejected`), sa ishodom i eligibility skorom.
- `POST /personas/{id}/memories/query` → rezultati sa razlaganjem skora.
- `POST /context/build` → paket za postojeći run, sa tekstom i hash-om.
- `POST /memories/{id}/supersede` → nova verzija; stara ostaje kao istorija.
- Upis: `persona_manager`, `system_admin`. Čitanje: sve uloge osim `viewer`.

## Usklađivanja van F4 (Canon ima prvenstvo)

1. **`run_id` za `memory.*` evente.** Kod je tražio `run_id` za svaki event van
   uske liste; Canon §7.1 ga traži samo za orchestration, runtime i policy evente
   unutar buđenja, a Canon §2 kaže da je za operatorske i sistemske zapise null.
   `memory.created` i `memory.contradiction_detected` su dodati u `RUN_ID_OPTIONAL`,
   a u njihovim šemama `run_id` dozvoljava null.
2. **Kockica rutine (F3).** Ključ je bio UUID reda `RoutineWindow`, pa je
   `seed_agent_001 --reset` menjao priču za isti seed. Sada je ključ
   `šablon:aktivnost:HHMM` — isti seed daje istu priču na svakom serveru (test).
3. **Geografija persone (F3).** `sr-Latn` nema region, pa geo signal nikad nije
   radio. Kad locale nema region, zemlju daje jezik (sr → RS).
4. **Početna strana** `/` — naziv, „interni sistem" i status aplikacije i baze.
   Bez ijednog podatka o personama, `noindex`.

## Šta F4 namerno ne radi

- **Izbor pravog embedding modela** — Canon §21; alat za merenje postoji.
- **Registar entiteta i graf** (`memory_entity`, `/knowledge/facts/{id}/graph`) —
  čeka Social Graph i prve stvarne upite.
- **Nedeljna i mesečna konsolidacija, LLM sažimanje** — čekaju LLM gateway;
  moraju da sačuvaju iste `derived` veze.
- **`memory_access_log`** — `MemoryContextPack` već beleži šta je model video.
- **Različite težine po profilu** — dok merenje ne pokaže da su potrebne.
- **API za pin i brisanje** — funkcije postoje; endpoint-i nisu u kanonskoj listi.

## Posledice

- Migracija `memory 0003`: `source_event_id` (UNIQUE po personi i tipu),
  `content_hash`, `tags`, `assertion_*`, `valid_from`/`valid_to`, `text_hash` na vektoru.
- Novi beat task (1 h). Seed računa vektore za svoje memorije.
- 235 testova (F4 dodaje 37).
