# ADR-0150 — WK Model Benchmark: motor za kvalitet-po-ceni modela

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Sa 300+ agenata izbor modela je ~100× razlika u ceni po zadatku,
  ali jeftin model koji ne prolazi je bezvredan (vlasnik: „Claude Haiku 5.5 ne
  valja ništa"). Treba nam metar koji meri **koji je najjeftiniji model koji i
  dalje PROLAZI** — po tipu zadatka, ne globalno.
- **Prethodi:** ADR-0011 (gateway `only=ruta` forsira tačan model), postojeći
  `LLMRoute` i `operator_run`.
- **Dodaje:** `apps/llm_gateway/benchmark.py` (motor), `manage.py benchmark`
  (komanda), `tests/test_benchmark.py`.

## Odluka
1. **Motor na postojećem gatewayu.** `pokreni(specovi, slucajevi, persona)` za
   svaku rutu (`provider:model_key`) pušta skup test slučajeva kroz
   `gateway.generate(only=ruta)` — isti put kao pravi rad, meri tokene i vreme
   po pozivu. Nema nove LLM infrastrukture.
2. **Cena iz realnih cenovnika, ne iz baze.** `CENE_USD_1M` drži proverene cene
   (USD/1M tokena, 12.11.2026.); `cena_usd(spec, tin, tout)` množi stvarne
   tokene realnom cenom. Izveštaj je tačan nezavisno od DB konfiguracije rute;
   nepoznat model → cena 0 i napomena.
3. **Provera je zasad DETERMINISTIČKA.** 5 slučajeva po kategorijama (CRM/JSON,
   Format, Srpski jezik, Rezonovanje): JSON se parsira, dijakritika se detektuje,
   broj redova/odgovor se proverava tačno. Bez LLM-sudije — sudija je sledeći
   slajs. Deterministička provera je jeftina, ponovljiva i ne troši dodatne
   tokene.
4. **Izveštaj po modelu i po kategoriji.** `zbir(rezultati)` daje po modelu:
   stopu uspeha, **cenu po uspešnom zadatku** (ukupna cena / broj prošlih — ne
   po pozivu, jer neuspeh je bačen novac), prosečnu latenciju, broj grešaka i
   razbijanje po kategoriji. Komanda to ispiše kao tabelu.

## Zašto ovako (prvi slajs)
- Poređenje više modela traži da svaki ima svoj pravi API model-id i
  konfigurisan ključ. Sada postoji ruta za `claude-sonnet-5`. Zato prvi slajs
  dokazuje **motor** na toj ruti; dodavanje svakog novog modela = konfigurisanje
  njegove rute (`ruta_za` je napravi ako fali), ne nov kod.
- „Cena po uspehu" je prava poluga: na 900k zadataka/mesec jeftin model koji
  pada na pola zadataka je skuplji od srednjeg koji prolazi.

## Posledice
- Imamo ponovljiv metar: `manage.py benchmark --rute anthropic:claude-sonnet-5`.
- Odluka o modelu po tipu zadatka postaje merljiva, ne utisak.

## Backlog (zasebni slajsevi)
- **Slajs 2 — LLM-sudija:** za zadatke gde deterministička provera ne hvata
  kvalitet (npr. ton, tačnost sadržaja), recenzent-model ocenjuje izlaz.
- **Slajs 3 — trajnost:** `BenchmarkRun` model + istorija, pa se vidi drift kroz
  vreme i poređenje po datumu.
- **Slajs 4 — PDF izveštaj** benchmarka (koristi postojeću `dokument.napravi`).
