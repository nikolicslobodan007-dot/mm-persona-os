# ADR-0127 — Sakupljač veština: isti ingest kao Veritas, ali vadi veštine

- **Status:** prihvaćen (04.11.2026.)
- **Povod:** Cilj — agenti sakupljaju veštine sa interneta kad im se pošalje samo
  screenshot ili link, uz pregled YouTube video fajlova. Sve cigle za to već
  postoje (napravljene za Veritas); treba ih samo preusmeriti.
- **Prethodi:** ADR-0125 (klip/ASR), ADR-0126 (slika/OCR), ADR-0059 (sme da sakuplja,
  ne sme da uzme — licenca), ADR-0074/0120 (uvoz + embedding), ADR-0086 (Gateway)

## Uvid
Veritas i sakupljač dele CELU mašinu, razlikuju se samo u izlazu:
- **ingest** (tekst iz sveta): web (`uvoz_web`), slika (`veritas.slika` OCR),
  klip (`veritas.klip` ASR) — isto za oboje;
- **destilacija** (tekst → nešto): Veritas vadi TVRDNJE (→ verdikt), sakupljač
  vadi VEŠTINE (→ korpus).

## Odluka

**1. Opšti destilator veština** — `apps/memory/sakupljanje/destilator.py`:
`destiluj(tekst, naslov, opis, napomena, maks, llm, suvo) → {vestine, ul, iz, cena, etiketa}`.
Jezgro (sistem/prompt/parser + filteri: bez ćirilice, koraci ≤320, min 2) izvučeno
iz `harvest_agency`, koji je sad refaktorisan da ga koristi (bez duplikata).
Nevezano za `.md` — izvor je svejedno.

**2. Jedinstven ingest** — `apps/memory/sakupljanje/ulaz.py`:
`procitaj(vrsta, vrednost, suvo)` za web/slika/fajl/klip; vraća {tekst, naslov, izvor, vrsta}.

**3. Komanda `sakupi`** — `--url | --slika | --fajl | --klip-url` → ingest → destiluj →
ispis veština + opc. `--izlaz` (.json za uvoz). YouTube radi kroz postojeći ASR (klip).

**4. Licencu NE pogađa sakupljač (ADR-0059).** Destilovana veština nosi napomenu o
poreklu („Licenca: PROVERITI pri uvozu"); kutija licence se bira pri `vestina` uvozu
u bazu znanja. Sakupljanje je dozvoljeno, prisvajanje nije.

## Posledice
- „Pošalji link/screenshot → dobijem veštine" radi odmah, preko istih cigli kao Veritas.
- YouTube pregled: trenutno zvuk (ASR). Dublji pregled (frejmovi + OCR slajdova/koda)
  je sledeći korak (Slice: YT frejmovi), po dogovoru „prvo most, pa frejmovi".
- Uvoz u korpus i rangiranje ostaju na postojećem `vestina`/embedding toku (ADR-0074/0120).

## Sledeće
- YT frejmovi → OCR (spoj klip ASR + slika OCR nad uzorkovanim frejmovima).
- Opc. `--uvezi` da `sakupi` sam pozove uvoz (kad se licenca reši automatski/interaktivno).
