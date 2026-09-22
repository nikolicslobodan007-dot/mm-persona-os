# ADR-0014 — Persona uči iz odluka urednika

- **Status:** prihvaćeno
- **Datum:** 22.09.2026.
- **Canon verzija:** 1.1 (dopuna §1: novi model u `content`)
- **Izvori:** Canon §1, §10, §15 · ADR-0009, ADR-0010, ADR-0012
- **Kod:** `apps/content/lessons.py`, `apps/content/models.py` (`EditorialLesson`),
  migracija `content 0005`, `apps/content/service.py` (prompt),
  `apps/content/management/commands/content_eval.py`, `api/views/policy.py`,
  `console/` (Odobrenja, strana persone), `tests/test_lessons.py`

## Kontekst

Cilj je organizacija u kojoj AI agenti rade umesto ljudi, na skali do 10.000
agenata. Čovek na poslu uči iz povratne informacije, pa to mora i agent. Do sada
su razlog odbijanja i izmena urednika ostajali samo u audit zapisu, pa bi
urednik istu grešku ispravljao i kod sledećeg nacrta i kod sledećeg agenta.

## Odluka

### 1. Pouka je zaseban zapis, a ne memorija

`EditorialLesson` ima sledeća polja: persona (prazna znači **svi agenti**), vrsta
(`rejected`, `edited`, `manual`), tekst pravila, primer pre i posle, akcija iz
koje je nastala, autor i `is_active`.

Pouka nije `MemoryItem`, iz dva razloga:

- ne sme da bledi po poluživotu (Canon §10.3);
- ne sme da zavisi od toga da li će je retrieval pronaći.

Zato ide **doslovno u svaki prompt za pisanje**, u sekciji „pouke urednika”,
najviše 10 za organizaciju i 10 za personu, od najnovije. Lokalni šablon je ne
koristi, jer nije model.

### 2. Kako nastaje

- **Odbijanje:** pouka je razlog, u obliku „Urednik je odbio nacrt: …”.
- **Izmena:** ako je urednik napisao pravilo, pouka je to pravilo. Ako nije,
  izmena se opisuje bez modela, poređenjem reči: najviše tri promene u obliku
  „«pre» → «posle»”, „ukloni «…»” ili „dodaj «…»”.
- **Ručno:** urednik upisuje pravilo na strani persone.
- **Obično odobrenje bez izmene ne pravi pouku.** Pouka koja već postoji (isti
  tekst, isti nivo) ne pravi se ponovo.
- U konzoli, uz Odbij i Izmeni, stoje dva polja: **„Zapamti kao pouku”**
  (uključeno) i **„Pouka važi za sve agente”** (isključeno). Tako se, na primer,
  odbijanje „šablon, ključ nije radio” ne upisuje kao pouka.
- Preko API-ja se pouka uvek pravi za tu personu. Nivo „svi” postoji samo u
  konzoli, jer je to svesna odluka urednika.

### 3. Nivoi

| Nivo | Važi za | Primer |
|---|---|---|
| Organizacija (`persona` prazna) | sve agente, i nove | „Srpske navodnice „…”.” |
| Persona | samo tog agenta | „Mila piše o B2B nabavci, ne o maloprodaji.” |

Pouka se ne briše, nego **isključuje** (audit `content.lesson.toggled`), jer
istorija učenja ostaje.

## Posledice

- Svaka nova persona od prvog dana nasleđuje kućni stil.
- Na skali od 10.000 agenata biće potreban i srednji nivo (tim ili uloga,
  npr. „prodaja”, „nabavka”) i sažimanje pouka kad ih bude mnogo. To dolazi uz
  model organizacije. Ovde je ostavljen prostor: nivo određuje jedno polje.
- Kanonski spisak modela u `content` dobija `EditorialLesson` (test vlasništva
  nad modelima je ažuriran).
- 396 testova (dodato 8).
