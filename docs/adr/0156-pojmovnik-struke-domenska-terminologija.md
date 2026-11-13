# ADR-0156 — Pojmovnik struke: domenska terminologija u bazi znanja

- **Status:** prihvaćen (13.11.2026.)
- **Povod:** Sudija (ADR-0154/0155) je oborio Sonnet na „buke" — ISPRAVAN vinski
  termin — jer Pravopis pokriva gramatiku, ne struku. Treba drugi sloj znanja:
  **domenska terminologija**, kao referenca sudiji i kao pomoć agentima da pišu
  tačno. Vlasnik: krenuti od vina/rakije (Kolibica) i metrologije (VIML/DMDM),
  pa širiti iz zvaničnih izvora.
- **Prethodi:** ADR-0055/0120 (Pravopis u bazi znanja + semantička pretraga),
  ADR-0154/0155 (LLM-sudija, savetodavni).
- **Dodaje:** `apps/content/pojmovnik.py`, komande `pojmovnik` i `embed_pojmovi`,
  `apps/content/data/pojmovnik-{vino-rakija,metrologija}.jsonl`. Menja
  `apps/llm_gateway/benchmark.py` (`_strucni_blok` u sudiju).

## Odluka
1. **Isti obrazac kao Pravopis-PRAVILA.** Po jedan `KnowledgeSource` po izvoru
   (zbog porekla), po jedna `KnowledgeFact` po terminu, `predicate="pojam.struke"`,
   semantička pretraga preko `znanje_vektori` (ADR-0120). `object_json`:
   `{termin, definicija, domen, sinonimi, izvor}`.
2. **Domen je polje, ne zaseban sistem.** `trazi_pojmove` pretražuje preko SVIH
   domena (vino, rakija, metrologija, …). Novi domen = nova .jsonl + red u `IZVORI`.
3. **Sudija dobija termine kao referencu.** `_strucni_blok(izlaz)` vuče relevantne
   termine i ubacuje ih u prompt sudije uz Pravopis, sa uputstvom „važeći, NE
   ispravljati ih kao greške". Tako „buke" prolazi. Best-effort (ADR-0009).
4. **Prva runda (94 termina):** vino/rakija (50, potvrdio praktičar — Kolibica) i
   metrologija (44, VIML/DMDM — zvanično). Definicije pisane/overene, ne izmišljene.

## Poreklo izvora
- Vino/rakija: validirao vlasnik kao praktičar; fina tehnička preciznost sa
  tehnologom po potrebi.
- Metrologija: „Međunarodni rečnik termina u zakonskoj metrologiji" (VIML),
  srpski prevod OIML V1, izdala Direkcija za mere i dragocene metale (DMDM, 2011).

## Posledice
- Sudija više ne obara tačne stručne termine; agenti dobijaju tačnu terminologiju.
- Uvoz: `manage.py pojmovnik --uvezi` (embeduje sam); pretraga `--trazi`, stanje `--stanje`.

## Sledeće (fazno, po dogovoru)
- Faza 2: zakoni i podzakonska akta (DRUGAČIJI oblik — članovi propisa, ne par
  termin-definicija; svoj cevovod, npr. `propis.clan`).
- Faza 3: sve publikacije sa `dmdm.rs/publikacije` → procesovanje → baza znanja.
- Širenje domena (gradnja, stomatologija, špedicija…) iz zvaničnih izvora.
