# ADR-0031 — Libri: sloj znanja (Veritas i biblioteka) u Persona OS-u

- **Status:** predložen (čeka odluku o jezgru — vidi „Uslov" na kraju)
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0006 (memorija), ADR-0021 (plan sa checkpointima), ADR-0020 (opsezi memorije)
- **Izvori:** `Veritas — Definicija i sistemski prompt v1.0` (27.07.2026), Libero Libri —
  Mašina, moduli 3, 3A, 8, 18, 21; kod `Bibliotekar/` i `Grinder/`
- **Canon:** §10 (memorija), §16.5 (audit), §21 (uslovi platformi)

## Problem

Slobodan ima napisan sistem za istraživanje i biblioteku — **Veritas** (jedan agent u
osam faza) i **Nadu** (sloj bibliotekara) — sa radnim prototipom u Pythonu. Nezavisno od
toga, Persona OS ima memoriju sa poreklom, pouzdanošću po izvoru, tvrdnjama i
protivrečnostima, i mašinu planova sa koracima.

Pročitano rame uz rame, to su **dva opisa iste stvari**. Veritasovo pravilo „svaka
tvrdnja je navodna dok se ne potkrepi, nema činjenice bez izvora" i Canon §10.4
(`provenance`, sadržaj sa `inferred` nikad ne izlazi kao činjenica) napisani su u razmaku
od dva meseca, istom rukom, o istom problemu.

Pitanje nije da li graditi Veritasa. Pitanje je da li ga graditi **po treći put**.

## Odluka (predlog)

### 1. Veritas je plan, ne novi orkestrator

Osam faza — Tragač, Čitač, Proveravač, Hroničar, Kartograf, Inspektor, Bibliotekar,
Čuvar — postaju **osam koraka u postojećoj mašini planova** (ADR-0021), sa obrađivačima
u novom modulu `apps/libri/steps.py`. Faza ima ulaz i izlaz; to je tačno ono što korak
plana jeste. Delegiranje, checkpointi, `MAX_STEPS` i audit dolaze besplatno.

Time se ispravlja i razlika između dokumenta i prototipa: prototip danas izvodi svih osam
faza kao **jedan poziv modelu** koji vraća jedan veliki JSON. To radi, ali se ne može
proveriti po fazama, ne može se ponoviti samo jedna faza, i pada u celini kad padne.

### 2. Šta se preuzima iz Persona OS-a kakvo jeste

| Veritas / Bibliotekar traži | Već radi |
|---|---|
| tvrdnja sa izvorom | tvrdnja (subjekat, predikat, vrednost) + `MemorySource` |
| „ne biraj pobednika među izvorima" | protivrečnosti bez izmišljenog pobednika (ADR-0006 §3) |
| pouzdanost po vrsti izvora | `confidence` po izvoru (javni web 0,60–0,85, `llm_inference` 0,25–0,55) |
| poreklo, fikcija se ne meša sa činjenicom | `provenance`; `inferred` nikad ne izlazi kao činjenica |
| bez duplikata pri ponovnom unosu | dedup po `source_event_id`, pojačavanje postojeće |
| pretraga po značenju | pgvector + hibridni retrieval + Context Builder |
| trag o svemu | audit append-only |
| tajne se ne pamte | writer odbija `SECRET_MATERIAL` |

### 3. Šta se stvarno dograđuje — i to je sve

1. **Registar entiteta i graf odnosa.** Kartoni osobe, organizacije i događaja, i veza
   sa tipom, izvorom i ocenom pouzdanosti veze. Danas odnos postoji samo posredno, kroz
   tvrdnju.
2. **Dvostruko vreme.** Kada se **desilo** i kada je **objavljeno** — dva polja, ne jedno.
   Hroničar bez toga ne postoji.
3. **Pouzdanost po pet osa** (pouzdanost, nezavisnost, blizina događaju, potkrepljenost,
   stabilnost) **po tvrdnji**, uz postojeći jedan broj po vrsti izvora. Uz pravilo koje
   dokument izričito traži: *„Više 'nezavisnih' izvora koji vode ka istom originalu =
   jedan izvor."*
4. **Dosije** — dvanaest sekcija, dokument za čoveka, izlaz poslednjeg koraka plana.
5. **Blok dokumenta kao izvor.** LKP šema iz Grindera (`lkp-0.1`: `block_id`,
   `document_id`, `text`, `heading_path`, `source{page,section}`, `permissions`,
   `quality`) preuzima se **kakva jeste** — nema razloga izmišljati drugu. Memorija danas
   pamti po događaju, ne po strani i sekciji dokumenta.

### 4. Ulazi: pošta i javni web, nikad prijava

Izvori su mejl (već radi: IMAP, sandučići, dolazna pošta) i javne stranice po pravilima
Aneksa A — istinit User-Agent sa kontaktom, `robots.txt`, jedan zahtev u sekundi po
hostu, uslovni GET, **nikad nalog i nikad „prihvatam"**. Time ugovorni rizik ne postoji,
a ne ublažava se.

Lokalna dokumentacija ulazi kroz `obrada.py`/Grinder postupak: LibreOffice za Word i
Excel, PyMuPDF za PDF, OCR za skenirano — sve lokalno, bez slanja ikome.

### 5. Ime

U kodu **`libri`**, u razgovoru LiberoLibriMašina. `llm` je u Persona OS-u već zauzeto
za jezički model (`apps/llm_gateway`), a dva značenja iste skraćenice u jednom sistemu su
kvar koji se plaća kasnije.

## Šta je odbačeno

- **Pisanje novog orkestratora za Veritasa.** Mašina planova postoji, testirana je i
  ume da delegira. Drugi orkestrator znači druga pravila zaustavljanja, drugi audit i
  dvostruko održavanje.
- **Druga baza za blokove.** pgvector već stoji. BM25 iz prototipa ostaje kao
  **rezerva bez modela** — to je dobra osobina prototipa, ne teret.
- **Prebacivanje celog Bibliotekara u Persona OS odjednom.** Prototip radi i koristi se.
  Prvo ulazi jedan tok — izvor → blokovi → tvrdnje → dosije — pa se meri.

## Posledice

- Nov app `apps/libri` (blokovi, entiteti, odnosi, dosije) uz postojeći `apps/memory`,
  ne umesto njega.
- `manage.py libri uvezi --iz <putanja|mejl|url>` i `libri dosije --izvor <id>`.
- Zlatni skup i `memory_eval` dobijaju pitanja nad dokumentima, ne samo nad memorijom
  persone — inače se ne zna da li je pretraga po strani i sekciji bolja ili gora.

## Uslov

Ovaj ADR važi samo ako je **Persona OS jezgro**, a Libero Libri domen iznad njega.
Modul 21 Libero Librija bira TypeScript/NestJS/BullMQ, a PickStar Volume 20 bira
NestJS/FastAPI/Temporal — tri steka za jednog čoveka. Dok ta odluka nije doneta i
zapisana, ovaj ADR ostaje predlog i po njemu se ne piše kod.
