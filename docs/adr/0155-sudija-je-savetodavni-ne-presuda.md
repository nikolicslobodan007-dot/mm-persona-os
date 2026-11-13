# ADR-0155 — Sudija je savetodavni (označava), ne presuda (obara)

- **Status:** prihvaćen (13.11.2026.)
- **Povod:** Prva živa proba sudije (ADR-0154) oborila je Sonnetov „format-tri"
  zbog reči **„buke"**, „ispravljajući" je u „buket". Ali vlasnik (domenski
  stručnjak): **„buke" je vinski termin (ukus/aroma vina, franc. *bouquet*),
  „buket" je cveće.** Sonnet je bio u pravu, **sudija je pogrešio** — izmislio
  grešku na domenskom terminu. Sudija je ukorenjen u Pravopis (gramatika), ali
  Pravopis ne pokriva struku, pa se na terminima oslonio na svoje (pogrešno) znanje.
- **Prethodi:** ADR-0154 (LLM-sudija).
- **Menja:** `apps/llm_gateway/benchmark.py`,
  `apps/llm_gateway/management/commands/benchmark.py`.

## Odluka
1. **Podrazumevano savetodavno.** Sudija ocenjuje i **beleži** nalaz
   (`sud_ok` ∈ {None, True, False} + `sud` obrazloženje), ali **ne menja**
   `uspeh` — stopa uspeha ostaje na determinističkoj (strukturnoj) proveri.
   `--detaljno` prikazuje nalaz kao `[sudija OK]` / `[sudija SPORNO: razlog]` —
   signal za ljudski pregled, ne presuda.
2. **Obaranje je opt-in.** `--sudija-obara` vraća strogi režim (uspeh = struktura
   I sudija) za one koji ga svesno žele.
3. **Obrazloženje duže** (200 znakova, bilo 120) — da se nalaz ne seče.

## Zašto
- LLM-sudija ume da bude **samouvereno pogrešan**, pogotovo na domenskim
  terminima koje Pravopis ne pokriva (vinarstvo, HoReCa). Obaranje rezultata na
  osnovu takve ocene daje **lažne padove** (Sonnet „buke"). Čovek/domenski rečnik
  je poslednja instanca; sudija je recenzent koji označava sumnjiva mesta.
- U produkciji isto: agent napiše → sudija označi → čovek (ili rečnik struke)
  potvrdi pre slanja klijentu.

## Posledice
- Score je pouzdan (struktura), a jezički nalazi su vidljivi za pregled bez
  lažnih padova.

## Sledeće (otvoreno, po želji)
- **Domenski rečnik** uz Pravopis kao druga referenca sudiji (vinski/MM termini).
- **Jači sudija** (Opus) — možda zna „buke".
- **Zlatni skup** „tačno/netačno" primera koje vlasnik potvrdi — da se i sam
  sudija izmeri (preciznost/odziv), pre nego što mu se išta poveri.
