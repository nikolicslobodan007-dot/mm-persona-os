# ADR-0020 — Memorija: opsezi agent / sektor / firma i pečaćenje u nivoe

- **Status:** prihvaćeno
- **Datum:** 24.09.2026.
- **Canon verzija:** 1.1 (menja §10.2 — vidi „Odnos prema Canon-u")
- **Izvori:** Canon §10.1–10.4, §3.12–3.13 · Memory v0.1 §8, §9 · ADR-0006, ADR-0017
- **Kod:** `apps/memory/sealing.py`, `apps/memory/models.py`,
  `apps/memory/retrieval.py`, `apps/memory/context.py`, `apps/memory/tasks.py`,
  `apps/memory/management/commands/memory_seal.py`, `common/enums.py`,
  `console/`, `tests/test_sealing.py`
- **Spoljni izvor obrasca:** OpenHuman Memory Tree (analiza u projektnom
  dokumentu „OpenHuman → Persona OS: četiri beleške", 24.09.). **Nijedan red
  njihovog koda nije prenet** — preuzet je samo obrazac; njihov projekat je
  GPL-3.0 i pisan u Rust-u.

## Kontekst

Dva problema koja F4 nije rešio, a oba se vide tek sa vremenom i brojem:

1. **Agent koji radi mesecima nakuplja hiljade zapisa.** Retrieval bira
   najboljih dvadesetak, ali bira među sve više kandidata; stari zapisi ne
   nestaju, samo tiho prestaju da pobeđuju. Ništa ne sažima istoriju.
2. **Svaki agent uči sam za sebe.** Na 10.000 agenata isto saznanje se otkriva
   iznova hiljadu puta, a nijedan ne zna šta zna sektor pored njega.

## Odluke

### 1. Tri opsega čitanja

`MemoryItem.scope`: `persona` (podrazumevano), `department`, `company`.

- `persona` — lični zapis; čita ga samo taj agent. Canon §10.2 ostaje na snazi
  za njega bez izuzetka.
- `department` — znanje sektora; čitaju ga svi koji su raspoređeni u taj sektor
  (ADR-0017).
- `company` — znanje firme; čitaju ga svi.

`persona` ostaje popunjena i kod zajedničkih zapisa i znači **ko je autor**, ne
ko sme da čita. Tako se svaki zajednički zapis prati do rada iz kog je nastao,
a strani ključ ostaje obavezan.

CHECK ograničenje: sektor je popunjen tačno kad je opseg sektorski.

### 2. Zajedničko se ne upisuje — ono nastaje

Nema API-ja ni ekrana kojim se piše sektorska ili firmska memorija. Ona nastaje
**samo pečaćenjem naviše**. Ovo je namerno: zajednička beležnica u koju svako
sme da piše za mesec dana postane smetlište, a njeno čišćenje niko ne radi.

### 3. Kaskada pečaćenja

```
12 zapisa jednog agenta o jednoj temi   → sažetak nivoa 1 (opseg: agent)
 5 takvih sažetaka iz istog sektora     → sažetak sektora
 5 sažetaka sektora, iz bar dva sektora → sažetak firme
```

Tema je **prva oznaka zapisa**; zapisi bez oznaka idu u korpu „ostalo".
Peča se samo tema koja pređe prag — struktura se ne gradi unapred. To je ono
što memoriju drži malom: ono što se ne ponavlja nikad ne dobije svoj sažetak.

Firmski nivo dodatno traži **najmanje dva sektora**. Jedan sektor koji mnogo
priča o sebi nije znanje firme.

### 4. Sažetak je deterministički, kao i dnevna konsolidacija

Sastavlja se od podataka (naslov teme, broj zapisa, do 12 stavki), **bez poziva
modela** — isti ulaz daje isti izlaz i ne košta ništa. Test to i proverava:
ako pečaćenje pozove model, test pada.

Izvori se **arhiviraju, ne brišu**, i svaki dobija vezu `DERIVED` do sažetka,
pa se svaka rečenica prati unazad. Izuzeci ostaju aktivni: **prekretnica**
(salience ≥ 0,80) i `PINNED` — isto pravilo koje već važi za dnevnu
konsolidaciju (Memory v0.1 §9).

Idempotentno: `source_event_id` je hash od (opseg, vlasnik, tema, nivo), pa
ponovljeno pokretanje ne pravi drugi sažetak.

### 5. Kada se radi

Lični sažeci idu uz postojeće noćno održavanje (kod agenta 03:xx, uz
konsolidaciju i bleđenje). Kaskada ka sektoru i firmi ide jednom dnevno u
04:xx UTC, kad su lični sažeci gotovi. Ručno: `manage.py memory_seal`,
uz `--show` koji samo pokaže koje su teme prepune.

### 6. Šta vidi model

Zajednički zapis u kontekstu nosi oznaku **„znanje sektora"** ili **„znanje
firme"**, pored postojećih oznaka („⚠ sporno", „izvod, ne činjenica"). Model
treba da zna da to nije njegovo sećanje nego pravilo kuće.

Konzola: kartica **Šta agent pamti** — svoji zapisi, svoji sažeci, znanje
sektora, znanje firme.

## Odnos prema Canon-u

Canon §10.2 kaže da je **svaka pretraga persona-scoped**. Ovaj ADR to menja
uže nego što izgleda:

- za `scope=persona` uslov ostaje doslovno isti (`scope=persona AND persona=…`);
- dodaju se dva opsega u koje **ne postoji put kojim bi tuđi lični zapis ušao**
  — zajednički zapis nastaje isključivo pečaćenjem, a pečaćenje uzima samo
  sažetke, ne izvorne zapise.

Indeksi su prošireni: `(scope, department, status)` i
`(persona, scope, level, status)`.

## Posledice

- Memorija agenta prestaje da raste linearno: stari zapisi se sklapaju u
  sažetke, a u pretrazi ostaje manje kandidata sa više značenja.
- Znanje prelazi granicu agenta prvi put — i to tek kad se pokaže da se
  ponavlja, ne na osnovu nečije procene.
- 474 testa (dodato 11).

## Šta ostaje

- Prag 12/5/5 je prva procena. Posle prvog meseca rada treba ga izmeriti na
  stvarnim podacima — premali prag pravi sažetke ni o čemu, preveliki ostavlja
  memoriju da raste.
- Sažetak je za sada spisak stavki. Kad merenje pokaže da je to pretanko,
  prirodan sledeći korak je sažimanje modelom uz **iste veze do izvora** —
  ali tek tada, i kao zasebna odluka.
