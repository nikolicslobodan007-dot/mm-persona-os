# ADR-0151 — OpenRouter i Groq kao OpenAI-kompatibilne rute

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Benchmark (ADR-0150) je dokazan na `claude-sonnet-5`, ali na jednom
  modelu nema šta da poredi. Da bismo merili *besplatno vs. plaćeno* po tipu
  zadatka, treba povezati bar jednog besplatnog/jeftinog provajdera. OpenRouter
  daje desetine `:free` modela iza jednog OpenAI-kompatibilnog endpointa.
- **Prethodi:** ADR-0150 (benchmark), ADR-0011 (`only=ruta`), ADR-0013 (ključ po
  personi), gateway OpenAI-kompatibilna putanja.
- **Menja:** `config/settings/base.py` (`LLM_CREDENTIALS`, `LLM_BASE_URLS`),
  `.env.prod.example`. **Bez izmene gateway koda.**

## Odluka
1. **Nijedna nova grana u gatewayu.** `_call_external` već ima OpenAI-kompatibilnu
   putanju (`Authorization: Bearer`, `POST {base}/chat/completions`) — to je tačno
   OpenRouter-ov i Groq-ov API. Dovoljno je registrovati provajdere:
   - `LLM_CREDENTIALS["openrouter"] = "env:OPENROUTER_API_KEY"` (Groq je već bio).
   - `LLM_BASE_URLS["openrouter"] = "https://openrouter.ai/api/v1"`,
     `LLM_BASE_URLS["groq"] = "https://api.groq.com/openai/v1"`.
2. **Ruta se pravi kroz benchmark.** `benchmark.ruta_za("openrouter:<model>")`
   napravi `LLMRoute` sa `is_openai_compatible=True`; `base_url` i ključ gateway
   pokupi iz podešavanja. `provider:model_key` se deli na PRVOM dvotačku, pa
   `openrouter:meta-llama/...:free` ispravno zadrži `:free` u `model_key`.
3. **Cena besplatnih = 0, i to je tačno.** `:free` modeli nisu u `CENE_USD_1M`,
   pa benchmark računa cenu 0 — što je realnost. Poređenje je onda: *da li
   besplatni model PROLAZI*, uz `claude-sonnet-5` kao plaćeni baseline.

## Bezbednost (ne menja se, samo se naglašava)
- Besplatni nivoi često treniraju na podacima. Zato `data_training_allowed` po
  ruti ostaje brana: besplatni provajder dobija SAMO javne test-podatke
  benchmarka, nikad persona/CRM/vlasnički sadržaj.
- Ključ ide kroz postojeći lanac `credential_ref`: persona-ključ → env → zajednički.
  Tajna je samo u `.env.prod`, nikad u bazi (ADR-0013).
- `LLM_EXTERNAL_ENABLED=true` je i dalje prekidač; bez njega sve ide na lokalni šablon.

## Posledice
- Dodavanje modela za merenje = konfigurisanje rute, bez koda.
- Sledeći korak: `benchmark --rute openrouter:...,anthropic:claude-sonnet-5 --detaljno`
  → prvi izveštaj besplatno vs. plaćeno po kategoriji.

## Napomena
- Stvarna dostupnost i limiti `:free` modela se menjaju; pogrešan `model_key`
  benchmark prikaže kao grešku u redu (ne ruši se), pa se lako zameni.
