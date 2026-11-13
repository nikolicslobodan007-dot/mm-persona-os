# ADR-0157: Propisi kao izvor u bazi znanja (zakoni, članovi, bez auto-sudije)

Status: Prihvaćeno · Datum: 2026-11-13

## Kontekst

Uz Pravopis (ADR-0055/0120) i Pojmovnik struke (ADR-0156), treba nam treći sloj
znanja: PRAVNI izvori. Persone i agenti treba da citiraju TAČAN član propisa, a
ne da ga parafraziraju po sećanju. Prvi propis je Zakon o metrologiji
(„Sl. glasnik RS", br. 15/2016) — jer je DMDM jedina merodavna ustanova za
oblast koja nam treba (povezano sa VIML uvozom, ADR-0156).

Zakoni su javni akti; skidanje i procesuiranje javno objavljenog teksta je
automatizacija ručnog posla, ne pristup tajnoj građi.

## Odluka

Isti obrazac kao Pojmovnik: po jedan `KnowledgeSource` po propisu (idempotentni
uvoz po `title`), po jedna `KnowledgeFact` po članu, `predicate="propis.clan"`,
semantička pretraga preko `znanje_vektori` (ADR-0120).

- Shema reda (.jsonl): `{propis, sl_glasnik, glava, clan, naslov, tekst}`. `tekst`
  je VERAN, doslovan tekst člana (uključujući numerisane tačke i stavove).
- `sl_glasnik` u svakom redu je zvanična referenca (merodavan izvor, ne
  komercijalni preprodavac koji je samo prevozno sredstvo do teksta).
- Pretraga: `trazi_clanove(upit)` — ako upit imenuje broj člana („član 26"), taj
  član ide prvi (egzaktno), pa se dopuni semantički. `clan(broj)` vraća tačan član.
- `trust=1.0` jer je tekst doslovan iz službenog glasnika.

## Namerno IZOSTAVLJENO: auto-sudija usaglašenosti

Ovaj modul je IZVOR (čita, nalazi, citira) — NE presuđuje da li je nešto „u
skladu sa zakonom". Pravna ocena je ljudski posao i nosi rizik; benchmark-sudija
je i za jezik savetodavni, ne presuda (ADR-0155), a za pravo tim pre. Modul daje
tačan član kao referencu; zaključak donosi čovek.

## Veza sa farm-agentom

Masovno prikupljanje (skidanje sirovih dokumenata sa zvaničnog izvora, po listi
prioriteta, dnevni ritam ~20 dokumenata, datumski od najnovijeg) je posao
farm-agenta na novom serveru. Agent čuva ORIGINAL (verno) i puni ovaj modul
(pretraživo) — dupla korist: i sirov dokument i strukturirani članovi.

## Posledice

- +apps/content/propisi.py, +komande `propisi`, `embed_clanovi`.
- +apps/content/data/propisi-zakon-o-metrologiji.jsonl (62 člana, 17 glava).
- Prvi pravni izvor u bazi; obrazac spreman za ostale propise koje agent donese.
