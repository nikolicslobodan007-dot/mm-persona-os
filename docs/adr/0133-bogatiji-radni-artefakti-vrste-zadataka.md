# ADR-0133 — Bogatiji radni artefakti: vrste zadataka (stavka 2)

- **Status:** prihvaćen (10.11.2026.)
- **Povod:** Persona je do sada pravila samo kratku objavu (`service.draft`,
  hardkodirano „Napiši kratku objavu"). A u veštinama već ima znanje za prave
  radne artefakte (battlecard, outreach sekvenca, plan naloga). Treba joj dati
  da ih napravi — bez novog motora.
- **Prethodi:** ADR-0131 (promocija po domenu), ADR-0096/0112 (veštine u
  kontekstu), ADR-0074 (actor user:)
- **Menja:** nova `apps/content/zadaci.py` (registar vrsta), nova komanda
  `apps/content/management/commands/agent_zadatak.py`, testovi.

## Odluka

**Vrsta zadatka = (`upit`, `uputstvo`).** Registar `ZADACI` drži nekoliko vrsta;
svaka kaže kojim UPITOM se sastavlja kontekst (da ADR-0131 digne baš pravu
veštinu u sloj „U celini (sa koracima)") i koje UPUTSTVO ide modelu (`{ulaz}` =
konkretan unos: konkurent, prospekt, nalog, tema).

Artefakt nastaje kroz **isti** `context.build` + `gateway.generate` kao objava —
nema novog motora. Lepa posledica ADR-0131: upit vrste (npr. „konkurentski
battlecard") dovuče tu veštinu sa koracima, pa agent IZVRŠAVA njene korake za
konkretan ulaz, ne izmišlja format.

Prve vrste: `objava`, `battlecard`, `outreach`, `plan-naloga`.

## Obim — showcase-first

`agent_zadatak` je showcase sloj: **ispisuje** artefakt, NE čuva. Razlog: javni
`ContentFormat` (POST/ARTICLE…) ne opisuje INTERNI radni artefakt (battlecard se
ne objavljuje na kanal, nema disclosure/repetition/pravopis mašineriju). Model
`Artefakt` + pregled su sledeći sloj, tek pošto vidimo izlaze — isto kako je
`potraznja` prvo bila samo-čitanje (ADR-0132).

## Posledica
- `agent_zadatak --vrsta battlecard --ulaz "Konkurent: X"` → bogat artefakt kroz
  živ Gateway, koji vuče ICP/battlecard veštine sa koracima.
- Sledeći sloj: persistencija (model + pregled), pa uvezivanje u planer/raspored
  (da agent sam bira vrstu po zadatku iz reda), pa — stavka 3 — prva prava akcija.
