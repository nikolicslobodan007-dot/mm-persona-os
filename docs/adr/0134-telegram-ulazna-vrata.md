# ADR-0134 — Telegram kao druga ulazna vrata firme

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Čovek sa direktorom (Ivana, DIR-00) priča iz konzole (ADR-0105).
  Treba i sa telefona — da piše Ivani kao osobi, bilo gde, asinhrono.
- **Prethodi:** ADR-0105 (razgovor/ulazna vrata), ADR-0017 (organizacija),
  ADR-0015 (kanali), ADR-0074 (actor pod proverenim identitetom)
- **Menja:** `config/settings/base.py` (TELEGRAM_*), nova `apps/channels/telegram.py`,
  `apps/channels/tasks.py` (dva taska), `config/celery.py` (rute + uslovni beat),
  testovi. Bez modela i migracije (offset u redisu).

## Odluka

**Telegram je samo druga ulazna vrata u isti mozak.** Most prosleđuje čovekovu
poruku kroz **postojeći `razgovor.posalji()`** — ista procena, delegiranje i
odgovor kao u konzoli. Nema nove logike posla.

**Asinhrono (Celery).** Webhook/bot ne sme da visi dok Ivana odradi lanac, pa:
poruka stigne → odmah „Primila, radim…" → `channels.telegram_odgovori` (queue
`persona.interactive`) odradi `posalji()` → Ivanin odgovor ode nazad. Ovo je i
ispravka sinhronog blokiranja iz konzole. Poll je `channels.telegram_poll`
(beat 5 s, queue `mail`); offset i lock u redisu (bez migracije, bez duplog
procesiranja).

**Bezbednost — allowlist.** Konzola ima login+2FA; Telegram nema ništa. Bot
odgovara SAMO ID-evima iz `TELEGRAM_ALLOWED_IDS`, mapiranim na `user:slobodan`;
svaki drugi ID se tiho ignoriše. Token se čita iz tajne
(`TELEGRAM_TOKEN_CREDENTIAL` → `env:TELEGRAM_BOT_TOKEN`), ne stoji u kodu.

**Uspavan dok se ne upali.** `TELEGRAM_ENABLED=false` podrazumevano → poll se ni
ne zakazuje (beat se dodaje samo kad je true). Uključenje = env + restart.

**Ostaje INTERNO.** Ti ↔ tvoj agent, kao konzola. Ne dira prekidač spoljnih
radnji i NIJE „agenti objavljuju na Telegram javno".

## Obim — v1
Samo tekst; polling. **Kasnije:** webhook (instant, preko Caddy-ja), prilozi
(slike/fajlovi kao u konzoli, ADR-0115), više vlasnika u mapiranju ID→actor.

## Posledica
- Pišeš Ivani sa telefona; odgovor stigne kad je posao gotov.
- Nulti trošak dok je ugašen; nijedan ID osim tvog ne može da zada posao.
