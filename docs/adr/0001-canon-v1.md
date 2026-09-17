# ADR-0001 — Usvajanje Canon v1.0

- **Status:** prihvaćeno
- **Datum:** 15.09.2026.
- **Canon verzija:** 1.0

## Kontekst

Postojećih 14 dizajn dokumenata (Koncept → Scale 20→100) pisano je sekvencijalno.
Svaki sledeći je delimično preimenovao pojmove iz prethodnog, pa je za isti
koncept postojalo do četiri rečnika: četiri liste statusa akcije, tri liste
`PersonaStatus`, tri skupa Django app-ova, dve nekompatibilne skale rizika,
dva opsega za isto polje raspoloženja.

Dizajn je bio konzistentan po logici. Problem su bila **imena** — a kod se ne
može pisati iz četiri rečnika.

## Odluka

Usvaja se **Canon v1.0** kao normativni rečnik. Pravilo prvenstva:

1. Canon
2. Kod i migracije u `main`
3. Dokument sa kasnijim brojem faze
4. Dokument sa ranijim brojem faze

Ostalih 14 dokumenata od danas su **objašnjenja i obrazloženja**, ne izvor
istine za imena. Njihove formule, pragovi i procedure ostaju netaknuti.

Ključne odluke: razdvajanje `ActionStatus` od `ExecutionOutcome`; razdvajanje
rizika (`risk_score` 0–100) od odluke (`PolicyEffect`), uz GREEN/YELLOW/RED kao
izvedenu oznaku; 12 Django app-ova; dualni ID (UUID + `public_id`); Playwright
bez stealth forkova; beat na 30 s; pilot u dve faze, 44 dana.

## Posledice

- `common/enums.py` je jedino mesto na kome sme stajati enum.
- `tools/canon_lint.py` odbija ime van Canon-a u CI-ju. Bez toga bi Canon bio
  još jedan PDF koji niko ne poštuje nakon druge nedelje.
- Errata (Canon §19) navodi šta ispraviti u svakom od 14 dokumenata pri
  sledećoj reviziji.

## Migracioni put

Nema — kod još ne postoji. Ovo je odluka doneta pre prvog reda.
