# ADR-0154 — LLM-sudija za benchmark, ukorenjen u Pravopis

- **Status:** prihvaćen (13.11.2026.)
- **Povod:** Deterministička provera „srpski" gleda samo IMA li dijakritike, ne i
  da li je srpski TAČAN. Nemotron 3.5 Super VL je dobio prolaz sa „vinedari
  pažljivo skupljaju spelo grožđe" — reči koje izvorni govornik odmah vidi kao
  greške (treba: „vinogradari pažljivo sakupljaju zrelo"). Struktura prolazi,
  jezik ne valja. Metar je naduvao jezički kvalitet.
- **Prethodi:** ADR-0150 (benchmark), ADR-0055/0120 (Pravopis u bazi znanja +
  semantička pretraga `recnik.trazi_pravila`).
- **Menja:** `apps/llm_gateway/benchmark.py`,
  `apps/llm_gateway/management/commands/benchmark.py`, `tests/test_benchmark.py`.

## Odluka
1. **Sudija je jači model.** `--sudija anthropic:claude-sonnet-5` uključuje
   ocenjivanje: za slučajeve sa `sudija` kriterijumom (zasad „srpski" i
   „format-tri") izlaz ide kroz model-sudiju koji vraća `{"prolaz", "razlog"}`.
   Slučaj prolazi samo ako prođe I determinističku proveru I sudiju.
2. **Ukorenjen u Pravopis Matice srpske.** Pre ocene, `_pravopis_blok` zove
   `recnik.trazi_pravila(izlaz)` (ADR-0120) i relevantna pravila ubacuje u
   prompt sudije kao referencu. Sudija ocenjuje po autoritativnom izvoru, ne
   samo po svom osećaju. Best-effort: ako pravila nisu uvezena, sudija radi i bez.
3. **Pad sudije ne obara slučaj.** Ako sam poziv sudije padne (mreža, ruta),
   vraća se `(True, "sudija pao")` — infrastruktura sudije ne sme da lažno obori
   model koji se meri. `--detaljno` prikazuje razlog ocene uz svaki slučaj.

## Posledice
- Benchmark sada meri i jezički kvalitet, ne samo strukturu. Super VL-ov srpski
  bi sa sudijom bio ispravno obeležen kao pad, a ne lažni prolaz.
- Deterministička provera ostaje za strukturu (JSON, broj redova, broj); sudija
  pokriva ono što regex ne može — ispravnost i prirodnost jezika.

## Napomena
- Sudija je LLM poziv sa svojim troškom (nije uračunat u cenu merenog modela).
  Za strožu ocenu koristiti jači sudija (opus) nego mereni modeli.
- Sledeće: proširiti kriterijume na druge prozne slučajeve; po potrebi zlatni
  skup „tačno/netačno" primera da se i sam sudija izmeri.
