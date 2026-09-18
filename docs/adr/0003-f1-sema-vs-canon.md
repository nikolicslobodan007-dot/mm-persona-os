# ADR-0003 — F1: usklađivanje Database & Django Schema v0.1 sa Canon v1.1

- **Status:** prihvaćeno
- **Datum:** 18.09.2026.
- **Canon verzija:** 1.1
- **Izvor:** MM Persona OS — Database & Django Schema v0.1
- **Kod:** `apps/*/models.py`, `apps/*/migrations/0001*`, `tests/test_models.py`

## Kontekst

F1 je trebalo da bude mehanički posao: prepisati 44 tabele iz Schema v0.1 u
Django modele. Nije bio. Schema v0.1 je pisana pre Canon-a v1.0, pa se na
23 mesta ne slaže sa njim — ponekad u imenu polja, ponekad u tome kom app-u
tabela pripada, a na tri mesta u tome koliko tabela uopšte treba da postoji.

Po pravilu prvenstva iz Canon §0 (Canon → kod u `main` → kasniji dokument →
raniji dokument), Canon je dobio svaki spor. Ovaj ADR postoji da bi se znalo
**gde** je dobio i **zašto**, jer će neko za pola godine otvoriti Schema v0.1
i pitati zašto kod izgleda drugačije.

Rezultat: **59 modela u 12 app-ova**, 21 migracija, 131 CHECK ograničenje.

## Odluka

Usvaja se F1 šema kako je opisano ispod. Schema v0.1 od danas je objašnjenje,
ne izvor istine za imena i vlasništvo tabela — isti status koji je ADR-0001
dao ostalim dizajn dokumentima.

---

## A. Premeštanje tabela između app-ova (Canon §1)

| Tabela | Šema v0.1 | Canon v1.1 | Zašto |
|---|---|---|---|
| `WorldEvent` | `orchestration` | **`behaviour`** | Događaj ulazi u reducer i menja stanje; plan je tek posledica stanja. |
| `MailMessage` | `runtime` | **`channels`** | Pošta je kanal (`ChannelType.EMAIL`), ne runtime. Zaseban model za email ne postoji. |
| `TraitProfile` | app za ponašanje | **`personas`** | Osobina je deo identiteta; stanje je deo ponašanja. |
| `Biography`, `LifeEvent`, `IdentityFact` | `identity` | **`personas`** | App `identity` ne postoji u Canon §1. |
| `MediaAsset`, `VisualProfile` | delom `content` | **`visuals`** | `visuals` drži vizuelni identitet, `content` drži tekst i objave. |

App `behavior` je preimenovan u `behaviour` (Canon §0.3) i `llm_gateway` je
dodat kao dvanaesti — šema ga nije imala.

## B. Tabele koje šema nije imala (13 novih)

| Model | App | Canon | Zašto ne može bez njega |
|---|---|---|---|
| `AgentRun` | orchestration | §6.1 | Bez njega plan i trošak nemaju za šta da se vežu; svaki event nosi `run_id`. |
| `ActionAttempt` | orchestration | §3.9, §6.1 | `ExecutionOutcome` opisuje pokušaj, ne akciju. Da živi na `Action`, `UNKNOWN_EFFECT` bi bio prepisan sledećim pokušajem — a to je jedini ishod koji ne sme u retry. |
| `StateDelta` | behaviour | §4.3 | Bez traga reducera nema dokaza da je determinističan, pa ni SIM_SEED reproducibilnosti. |
| `MemorySource` | memory | §10.4 | `provenance` je vrsta porekla; ovo je konkretan trag — koji run, koji URL, koji izvor. |
| `MemoryContradiction` | memory | §10.4 | Protivrečnost ima životni ciklus (neko je rešava); veza bez statusa to ne izražava. |
| `MemoryContextPack` | memory | §16.3 | Bez zapisa šta je ušlo u prompt, „memory precision ≥ 95%" je nemerljiv na produkciji. |
| `CapabilityGrant` | policy | §6.4, §15.2 | Administrativna dodela sa dokazom i rokom. |
| `TrustState` | policy | §9.5 | `(persona, capability) → level` sa brojačem automatskih padova. |
| `KillSwitch` | policy | §9.6 | Hijerarhija GLOBAL→ACCOUNT i merenje vremena do poslednjeg zaustavljenog worker-a. |
| `PolicyIncident` | policy | §2.2, §12.5 | `INC-20260918-001`; SEV1 kod §9.4, SEV3 kod otvorenog breaker-a. |
| `ReconcileTask` | runtime | §12.3 | Reconcile je obavezan korak i nedostaje u Implementation Pack v0.1 (errata §19). |
| `VoiceProfile` | personas | §5 | Stil je bio pomešan sa karakterom; voice consistency ima svoj prag u kapijama. |
| `LLMRoute`, `PromptRecord`, `LLMUsage` | llm_gateway | §1, §13.2 | Ceo app je nov. |

## C. Preimenovanja i uklonjena polja

| Šema v0.1 | F1 | Canon | Napomena |
|---|---|---|---|
| `PolicyEvaluation` | `PolicyDecision` | §1, §6.2 | Evaluacija je radnja; odluka je zapis na koji se akcija poziva. |
| `Action.risk_level` (GREEN/YELLOW/RED) | `risk_score` (int 0–100) + `risk_class` | §3.6–3.7 | Tri stvari koje je šema spajala: skor je svojstvo zahteva, `PolicyEffect` je odluka, zona je izvedena i **nikada se ne upisuje**. Isto važi i za `ContentItem`. |
| `MemoryItem.importance` | `salience` | §10.1 | Formule eligibility i retrieval čitaju `salience`; dva imena za istu veličinu su bila izvor neslaganja. |
| `MemoryKind` (velika slova) | `MemoryType` (mala) | §3.12 | Vrednosti su ključevi `MEMORY_HALF_LIFE_DAYS` i `MEMORY_LAMBDA`. `RELATIONSHIP` → `social`. |
| `BehaviourState`: 6 polja | 18 polja | §4.2 | `mood` → `valence` (−1…1, jedino negativno polje) + `arousal`; stara imena opterećenja i društvene sklonosti ukinuta; dodati `focus`, `novelty_need`, pritisci, `free_minutes`, `attention_remaining`. |
| `TraitProfile`: 11 kolona | 12 kolona | §5 | `verbosity` ispada (stil → `VoiceProfile`); ulaze `commercial_intensity`, `contrarian`, `evidence_preference`. Pet polja iz Persona Spec-a idu u `traits_ext`. |
| `ContentItem.content_type` | `format` | — | Sudara se sa `django.contrib.contenttypes`. |
| `CostLedger.cost_amount` + `currency` | `amount_eur_cents` + `source_currency` + `source_amount_minor` + `fx_rate` + `fx_date` | §13.1 | Dva reda u dve valute se ne mogu sabrati bez kursa i datuma, a cost governor sabira svakog sata. |
| `CostLedger.service` | `cost_bucket` | §13.2 | Enum od osam vrednosti; `x_api_credits` je zaseban jer X naplaćuje po objavi. |
| `PolicyEffect.RATE_LIMIT` | `THROTTLE` | §3.5 | |

## D. Dodata polja na postojeće tabele

- `Persona`: `runtime_environment`, `trust_level`, `config_ext` (§3.2, §3.11, §5).
- `ChannelAccount`: `identity_vehicle`, `disclosure_label_status`,
  `named_human_admin` (§3.14, §3.16, A-01/A-02/A-03) i pet polja za poštu —
  `persona_address`, `sending_domain`, `dkim_selector`, `warmup_started_at`,
  `daily_cap` (§12.8).
- `BrowserProfile`: `allowed_domains`, `blocked_domains`,
  `max_session_seconds`, `kill_switch_enabled`, `auth_state`,
  `snapshot_version` (§12.7).
- `Action`: `policy_decision`, `content_hash`, `deadline_at`, `max_attempts`
  (§6.2, §15.3, §12.6, §12.4).
- `MediaAsset`: `public_id` oblika `IMG-P00001-0047` (§2.2).
- `MemoryItem`: `status`, `provenance`, `goal_relevance`, `novelty`,
  `sensitivity` (§3.13, §10.2, §10.4).
- `RuntimeSession`: `heartbeat_at`, `lease_expires_at`, `is_write` (§12.2–12.3).

## E. Invarijante sprovedene u bazi, ne u servisu

Četiri hard KPI-ja iz Canon §16.5 ne smeju zavisiti od toga da li je neki
servisni sloj zaboravljen:

| KPI | Mehanizam |
|---|---|
| `actions_without_policy_decision = 0` | CHECK `action_requires_policy_decision` — od `QUEUED` nadalje `policy_decision_id` mora postojati. |
| `duplicate_side_effects = 0` | `Action.idempotency_key` UNIQUE NOT NULL. |
| L3/L4 se ne mogu dodeliti | CHECK na `Persona`, `CapabilityGrant` i `TrustState` (§3.11, A-08). |
| TikTok/YouTube nalozi ne postoje | CHECK `channel_account_no_out_of_scope` (§16.2, A-10). |

Uz njih: `browser_profile_engine_playwright_only` (§12.1 — stealth fork je u
koliziji sa §9.4 tačkom 4) i `runtime_session_one_write_per_persona` (§12.2).

## F. Tehničke odluke bez osnova u dokumentima

1. **Radni enum-i žive u `common/enums.py`.** Canon §3 normira 24 enum-a;
   šema traži još 24 vrednosti nabrojane u koloni „Pravilo / relacija"
   (`open/selected/rejected/used` i slično). Canon §20 tačka 3 kaže da enum
   van `common/enums.py` ne postoji i `tools/canon_lint.py` to sprovodi, pa
   su i oni tamo — u odvojenoj sekciji, ispod linije, sa pravilom da vrednost
   koja uđe u ugovor ili u policy DSL prelazi gore kroz ADR.
2. **Uređene torke za DB ograničenja.** `frozenset` ima nedeterministički
   redosled, a `makemigrations` upisuje sadržaj liste u migraciju — svaki
   `--check` bi prijavljivao lažnu izmenu. Zato postoje
   `ASSIGNABLE_TRUST_LEVEL_VALUES` i `OUT_OF_SCOPE_CHANNEL_VALUES`.
3. **Migracije nisu 0001–0014 iz šeme §20.** Django sam deli inicijalne
   migracije po app-u i rešava kružne zavisnosti (`Action ↔ PolicyDecision`,
   `ChannelAccount ↔ BrowserProfile`); rezultat je 21 fajl umesto 14. Plan iz
   šeme ostaje tačan po redosledu sadržaja, ne po broju fajlova.
4. **`CREATE EXTENSION vector` je prva operacija u `memory/0001`,** umesto
   zasebne migracije `0001_common_extensions` — `memory` je jedini app koji je
   koristi.
5. **HNSW indeks stoji u modelu,** ali Canon §10.5 traži da se u produkciji
   kreira `CONCURRENTLY` i tek posle merenja recall/latency. Do tada je
   sekvencijalno pretraživanje prihvatljivo (na 5 persona ispod 50 ms).

## Posledice

- Schema v0.1 se više ne čita kao izvor imena. Gde se razlikuje od koda,
  kod je u pravu i ovaj ADR kaže zašto.
- `tests/test_models.py` čuva 12 mapa vlasništva nad modelima i imena polja —
  premeštanje tabele u drugi app ili povratak ukinutog imena ruši test.
- Otvoreno, za zaseban ADR: **centralna suppression lista** za odlaznu poštu.
  Canon §12.8 tačka 6 je traži („odjava kod jedne persone važi za sve"), a
  Canon §1 nema model za nju. `MailMessage.unsubscribed` beleži pojedinačnu
  odjavu, ali ne nosi listu — to je polumera i tako je treba čitati.
- Otvoreno, za zaseban ADR: **hash lanac nad `AuditEvent`.** `payload_hash`
  postoji, ali bez `prev_hash` audit se može preurediti neprimetno. Nije
  dodato jer za to nema osnova ni u Canon-u ni u šemi.
