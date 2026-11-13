# ADR-0153 — Google Gemini kao OpenAI-kompatibilni provajder

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Gemini (`gemini-flash-latest`) već radi odlično na srpskom u
  produkciji (Viberče), preko Google API ključa. To je proveren kandidat za
  srpske zadatke — treba ga izmeriti u benchmarku uz ostale.
- **Prethodi:** ADR-0151 (OpenRouter/Groq kao OpenAI-kompatibilni), ADR-0150
  (benchmark).
- **Menja:** `config/settings/base.py`, `apps/llm_gateway/benchmark.py`,
  `.env.prod.example`. **Bez izmene gateway koda.**

## Odluka
1. **Google preko svog OpenAI-kompatibilnog endpointa.** Google nudi
   `https://generativelanguage.googleapis.com/v1beta/openai`, pa ide istom
   OpenAI-kompatibilnom putanjom gatewaya (`Authorization: Bearer`,
   `/chat/completions`) — nikakav nov kod. Registruje se:
   - `LLM_CREDENTIALS["google"] = "env:GEMINI_API_KEY"`
   - `LLM_BASE_URLS["google"] = ".../v1beta/openai"`
2. **Koristi postojeći Google ključ.** Isti `GEMINI_API_KEY` kao Viberče, u
   `.env.prod` (tajna, nije u gitu). Nije throttlovan free nivo kao OpenRouter
   `:free`, pa daje čist rezultat.
3. **Cena `gemini-flash-latest` je približna** (0.75/3.75 USD/1M, kao flash) dok
   se ne potvrdi tačan cenovnik; stopa uspeha je ionako glavna mera.

## Posledice
- `benchmark --rute google:gemini-flash-latest,...` meri proveren srpski model.
- Ako Gemini bude najjeftiniji-koji-prolazi za srpske zadatke, to je jak kandidat
  za radnog konja (i već ga imamo podešenog u produkciji).

## Napomena
- `gemini-flash-latest` je alias; ako Google promeni na šta pokazuje, benchmark
  to vidi kao grešku u redu (ne pada). Za fiksno merenje koristiti verzionisan ID.
- Besplatni Gemini nivoi mogu trenirati na podacima; benchmark šalje samo javne
  test-podatke, a `data_training_allowed` po ruti ostaje brana za pravi rad.
