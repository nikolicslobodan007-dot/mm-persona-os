# ADR-0114 — Bot se predstavlja kao WebKorporacijaBot

- **Status:** prihvaćen (18.10.2026.)
- **Povod:** Agenti žive na WebKorporacija.com i nemaju veze sa drugim
  domenima (vlasnikovo pravilo). Deklarisani User-Agent je i dalje bio
  `MercatoMasterBot/1.0 (+https://mercatomaster.com/bot; …)`. Pre nego što
  ijedan agent dodirne tuđi server, bot mora da se predstavlja svojim imenom
  i da vodi na stranu koja zaista postoji (`webkorporacija.com/bot`).
- **Prethodi:** Canon §6.4, §12.6 (obavezni parametri za `web.read_public`)
- **Menja:** `policy/capabilities.yaml` (izvor istine), `config/settings/base.py`,
  `.env.example`, `.env.prod.example`, `tests/conftest.py`, `tests/test_runtime.py`

## Odluka

Deklarisani UA je sada:

```
WebKorporacijaBot/1.0 (+https://webkorporacija.com/bot; bot@webkorporacija.com)
```

**Izvor istine je `policy/capabilities.yaml`** —
`web.read_public.required_constraints.user_agent_declared`. Odatle ga čita
`apps/runtime/adapters/web.py:user_agent()` i to se zaista šalje kao zaglavlje;
`apps/policy/engine.py` proverava da predloženi ugovor nosi tačno taj UA.
Pošto je `capabilities.yaml` upečen u sliku, deploy nosi novu vrednost — nema
izmene `.env.prod` na serveru.

**`settings.WEB_READ_USER_AGENT` je mrtav** — nijedan kod ga ne čita (izvor je
`capabilities.yaml`). Svejedno je promenjen, da niko kasnije ne zakači pogrešnu
vrednost, i da u repou ne ostane nijedan trag tuđeg domena.

## Veza sa stranom `/bot`

Ovaj UA vodi na `https://webkorporacija.com/bot` — stranu koja već postoji
(`sajt/bot.html`): ko je bot, šta čita, šta nikad ne radi, kako da ga zaustave
preko `robots.txt`. Deklaracija i strana moraju da ostanu usklađene.

## Šta ovo NE radi

- **Ne pali spoljne radnje.** `GLOBAL_EXTERNAL_ACTIONS_ENABLED=false` ostaje;
  ovo je samo ispravan identitet za kad se prekidač jednom upali.
- **Ne menja pravila ponašanja bota** (robots, 1 QPS, conditional GET) — samo
  ime pod kojim se predstavlja.
