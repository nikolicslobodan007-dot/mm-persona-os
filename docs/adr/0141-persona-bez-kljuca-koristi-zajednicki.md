# ADR-0141 — Persona bez svog ključa koristi zajednički (LLM_REQUIRE_PERSONA_KEY=false)

- **Status:** prihvaćen (11.11.2026.)
- **Obrće:** ADR-0013 dopuna (24.09) — „svaki agent ima svoj ključ; bez njega
  ne pozajmljuje zajednički, nego mu nacrte piše lokalni šablon".
- **Povod:** Dijagnostika 11.11. (vidi dopunu-stanja-11-11-web-sazetak…):
  živi posao ide kroz delegaciju, a dete-plan izvršioca koristi personu
  izvršioca (npr. P-00020), koja **nema svoj ključ**. Uz
  `LLM_REQUIRE_PERSONA_KEY=true`, `credential_ref` vrati `(None,'none')` →
  `gateway.generate` tiho pređe na lokalni šablon. Posledica: samo je direktor
  (ima ključ) „mislio" modelom, a **svaki delegirani posao** (praktično sav
  rad) mesecima je bio kalup. To je bio koren svih „šupljih" izlaza.

## Odluka
Podrazumevano `LLM_REQUIRE_PERSONA_KEY=false`: persona bez svog ključa pada na
**zajednički** anthropic ključ (`LLM_CREDENTIALS`). Tako svaki delegirani korak
dobija pravi model. Persona koja IMA svoj ključ i dalje koristi svoj (prednost,
ADR-0013/0026) — ovo menja samo ponašanje za one BEZ ključa.

- Kod (`config/settings/base.py:236`) je već imao default `false`.
- `.env.prod` na serveru je imao eksplicitno `true` → prebačeno na `false`
  (živo, `up -d`).
- `.env.prod.example` je imao `true` → prebačeno na `false` sa objašnjenjem,
  da svež server ne dobije staro ponašanje.

## Posledice
- Trošak delegiranih poslova ide na zajednički ključ (dok se personama ne daju
  svoji ključevi). Za sada prihvatljivo — sve na istom vlasniku.
- Ko hoće strog trošak po personi: `LLM_REQUIRE_PERSONA_KEY=true` + svaki
  izvršilac dobije svoj ključ (inače mu posao pada na kalup).
