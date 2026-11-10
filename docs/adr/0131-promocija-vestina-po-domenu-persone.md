# ADR-0131 — Promocija veština po domenu (niši) persone

- **Status:** prihvaćen (10.11.2026.)
- **Povod:** `agent_proba --pun-kontekst` (P-00001, „AI agenti u prodaji")
  pokazao je da sloj „U celini (sa koracima)" (`VESTINE_PUNIH=4`) popunjavaju
  meta-veštine *o AI agentima* (engineering, uprava), dok prave **prodajne**
  veštine (ICP, Challenger, battlecard) ostaju u repu „Još veštine…", bez
  koraka. Semantički rang (ADR-0120) favorizuje doslovno poklapanje tokena
  „AI agent", a „prodaja" je jedan token od tri i ne dovuče engleske `sales`
  veštine dovoljno visoko.
- **Prethodi:** ADR-0120 (semantičko rangiranje), ADR-0101 (rang veština po
  sektoru), ADR-0112 (indeks + pune, budžet), ADR-0005 (niše persone)
- **Menja:** `apps/memory/context.py` (`_rangiraj_vestine` + helperi), testovi.
  Bez migracije, bez ponovnog uvoza, bez promene organizacije.

## Povod detaljno — tri uzroka, ne jedan

1. **Persona nema sektor.** `seed_agent_001.py` ne pravi `Assignment`, pa
   `_sektor_persone(Mila)` je prazno — leksički put (koji poštuje sektor) ne
   može da pomogne jer je `svoj=0` za svaku veštinu.
2. **Destilovane veštine imaju prazan `source.sector`.** Uvoz (`vestina.py`)
   validira `--sektor` po `Department.code` i odbija izmišljen sektor; divizije
   idu kao `sales/marketing/engineering` (engleski, mala slova), a departmani su
   `PRODAJA/MARKETING/RAZVOJ` — pa su uvezene sa praznim sektorom. Divizija živi
   samo u naslovu i u **sirovoj napomeni** (`Destilovano iz agency-agents/<div>/…`).
3. **Semantički put ignoriše sektor** — čist kosinus.

## Odluka

**Most je niša, ne department.** Persona već ima niše sa težinama
(`PersonaTagLink`, kategorija `niche`): Mila ima `ai 0.9, b2b 0.9, sales 0.7`.
Ključevi niša su u **istom rečniku** kao divizije korpusa (`sales`, `marketing`,
`engineering`…) — oba engleska — pa nema srpsko-engleskog jaza koji je i naterao
ADR-0120 na semantiku.

Posle semantičkog (ili leksičkog) poretka, `_promovisi_domen` **stabilno** diže
veštine čija divizija poklapa nišu persone:

- divizija se čita iz sirove napomene (`agency-agents/<div>/`); izvori bez
  divizije (GitHub Signals: „Sakupljeno iz web: …") nemaju podsticaj;
- ključ sortiranja je `-težina_niše(divizija)`; `sorted` je stabilan, pa unutar
  iste težine ostaje kosinusni/leksički redosled;
- veštine bez poklapanja imaju težinu 0 i ostaju na kraju, u zatečenom poretku;
- **bez niša → no-op**: persone bez niša i stari testovi rade kao pre.

Namerno: niša `ai` i `b2b` **nemaju** odgovarajuću diviziju i ne diraju poredak —
generička „ai" niša ne sme da gura sve veštine o AI u gornji sloj; to bi vratilo
tačno problem zbog koga je ADR i nastao. Samo `sales` (= divizija `sales`) radi,
i daje prodajne veštine u sloj „U celini".

## Posledica

- Za P-00001 i „AI agenti u prodaji": sloj „U celini" popunjavaju 4 semantički
  najbliže **prodajne** veštine; meta-veštine o AI padaju u indeks (agent ih i
  dalje zna po imenu i traži korake kad zatrebaju — most ka demand-driven ulovu).
- Rešenje je po persona-domenu, pa radi za svaku personu i svaki budući korpus
  bez taggovanja sektora i bez preslikavanja divizija na departmane.

## Alternative (odbijene)

- **Backfill `source.sector` + `Assignment` + sektor-svestan semantički rang.**
  Organizaciono veran, ali traži lossy preslikavanje divizija → `Department.code`
  (gde ide `product`, `specialized`, `design`?), dodelu persone i ponovno
  taggovanje. Veći zahvat za isti efekat. Ostaje kao opcija ako niše ikad
  prestanu da budu dovoljan signal.
- **Blend kosinus + leksički podsticaj po tekstu veštine.** Subjekt je srpski,
  „ai" je svuda — vratio bi meta-AI veštine na vrh.
