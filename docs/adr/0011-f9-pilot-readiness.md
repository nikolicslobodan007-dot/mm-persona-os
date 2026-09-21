# ADR-0011 — F9: Spremnost za pilot (status persone, kopije, merenje modela)

- **Status:** prihvaćeno
- **Datum:** 21.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §3.1, §13, §16, §21
- **Kod:** `apps/personas/lifecycle.py`, `api/views/personas.py` (`/status`),
  `console/` (kartica Status), `apps/content/management/commands/content_eval.py`,
  `deploy/backup.sh`, `deploy/restore_check.sh`, `tests/test_lifecycle.py`

## Kontekst

Pre pilota su ostala tri otvorena pitanja:

1. **Mila je READY i scheduler je ne budi.** Scheduler budi samo ACTIVE
   (`WAKEABLE_BY_SCHEDULER`), pa se rutine i nacrti iz F7 ne pokreću sami.
   Status nije mogao da se promeni ni kroz API ni kroz konzolu, jer ga PATCH
   namerno ne prima.
2. **Kopija baze** postoji kao skripta, ali nije zakazana i nikad nije vraćena.
3. **Izbor modela.** Lokalni šablon brzo počne da se ponavlja: merenje na
   6 tema daje najveću sličnost 0,79, a prag odbijanja je 0,8.

## Odluke

### 1. Status persone ima svoj put i tabelu prelaza

`lifecycle.change_status(persona, to, actor, roles, reason)` je jedini put.
Razlog je obavezan, a svaka promena upisuje audit (`persona.status.changed`,
WARNING) i povećava `version`.

| Prelaz | Ko |
|---|---|
| DRAFT → READY | persona_manager, system_admin |
| READY → ACTIVE, PAUSED → ACTIVE, READY → PAUSED | operator, persona_manager, system_admin |
| ACTIVE → PAUSED | isto + runtime_admin, trust_safety |
| ACTIVE → SUSPENDED, SUSPENDED → READY, DEGRADED → ACTIVE | **samo** trust_safety |
| → ARCHIVED | system_admin |

- READY → ACTIVE traži stanje ponašanja i bar jednu uključenu rutinu. Posle
  aktivacije `next_wake_at` se postavlja na sada, pa je scheduler budi odmah.
- Povratak iz SUSPENDED namerno ne sme `system_admin` bez uloge `trust_safety`
  (Canon §3.1: bezbednosna odluka).
- API: `POST /api/v1/personas/{id}/status` je dopuna Canon §8.2 ovim ADR-om.
- Konzola: kartica **Status** na strani persone nudi samo prelaze dozvoljene
  ulozi prijavljenog korisnika.

### 2. Kopija koja nije vraćena nije kopija

- `backup.sh` svake noći u 03:15 pravi `pg_dump` i arhivu MinIO-a, čuva ih
  14 dana i pravi `pg-latest.dump`.
- `restore_check.sh` svake nedelje u 04:30 vraća poslednju kopiju u
  privremeni Postgres kontejner, broji persone, akcije, audit i migracije, pa
  briše kontejner. Neuspeh znači izlaz 1 i red u `restore.log`.
  Produkcijska baza se ne dira.
- Kopija van servera: Hetzner backup (ceo disk, već uključen), plus ručno
  preuzimanje `pg-latest.dump` na PC po potrebi. Zaseban skladišni nalog
  čeka odluku o trošku.

### 3. Model se bira merenjem, ne utiskom

`manage.py content_eval` za svaku `content_draft` rutu (lokalni šablon i svaka
uključena spoljna) pravi nacrte na **istim** temama, sa **istim** kontekstom
iz memorije. Meri:

- tvrde zabrane (mora biti 0);
- udeo latinice i nacrta sa dijakriticima (persona piše sr-Latn);
- ponavljanje između nacrta, dužinu, trajanje i trošak.

Nacrti se ne čuvaju kao sadržaj i ne idu na odobrenje. Ostaju samo tragovi
poziva i trošak.

`LLMRoute` se dodaje u bazu tek kad se izabere provajder. `gateway.generate(only=…)`
meri tačno jednu rutu, bez prelaska na sledeću.

### 4. Sitne ispravke konzole

- Decimalni brojevi su se lokalizovali („0,700"), pa su `<meter>` trake bile
  prazne. Sada se koristi `unlocalize`.
- Pažnja se meri prema dnevnom budžetu, a ne prema 1.
- „Sledeće buđenje" više ne prikazuje 1970. godinu. Za personu koju scheduler
  ne budi piše zašto.

### 5. Javni tekst citira samo znanje (dopuna 21.09.)

Prvi automatski nacrt na serveru doslovno je preuzeo unutrašnju proceduru
(„Pre svake objave: izvor za svaku tvrdnju…”) i zapis buđenja („Nacrt objave
u prozoru weekday 12:30–13:30”). Uzrok: lokalni šablon je kao „činjenice”
uzimao prve dve stavke iz memorije, bez obzira na vrstu.

Sada u tekst i u `citations` idu samo `semantic` i `content` stavke
(`QUOTABLE_MEMORY`). Procedure, epizode i odnosi ostaju u kontekstu za model,
ali se ne citiraju. Test: `test_internal_memories_never_leak_into_text`.

## Posledice

- Kada operater aktivira Milu, rutina radi sama. Prozori „post" prave nacrte
  koji čekaju odobrenje u konzoli i ističu za 2 h.
- Sa lokalnim šablonom deo nacrta biće odbijen kao ponavljanje. To je
  očekivano i meri se.
- 380 testova (F9 dodaje 10, b211afc 1, ova dopuna 1).
