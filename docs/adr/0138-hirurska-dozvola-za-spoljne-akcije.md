# ADR-0138 — Hirurška dozvola za spoljne akcije (stavka 3, prvi presek)

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Kapija spoljnih akcija je robusna (tri sloja: `policy/gateway.py`,
  `runtime/transport.py`, `runtime/executor.py`; `external_live` + persona u živom
  okruženju + odobrenja + trust + kill-switch). Ali jedini prekidač za PALJENJE
  je **globalni** (`GLOBAL_EXTERNAL_ACTIONS_ENABLED`) — sve-ili-ništa. Za PRVU
  pravu akciju treba hirurška dozvola: tačno jedna persona, kanal i tip.
- **Prethodi:** Canon §6.2 (kapija), ADR-0099 (uži prekidač za čitanja)
- **Menja:** `config/settings/base.py` (`EXTERNAL_ACTIONS_ALLOWLIST`),
  `apps/policy/gateway.py` (`external_live` + helperi), testovi.

## Odluka
`external_live` dobija treći uslov za spoljne EFEKTE: lista
`EXTERNAL_ACTIONS_ALLOWLIST` (unosi `persona_public_id|channel_type:handle|action_type`,
`*` = bilo šta).

- **Prazna lista → bez ograničenja** (globalni prekidač je jedini uslov, kao do
  sada). Zato je promena ne-lomljiva: postojeći testovi sa prekidačem ON žive.
- **Neprazna lista → spoljni efekat ide SAMO za navedene** (persona, kanal, tip).
- **Čitanja** (`READ_ACTION_TYPES`) su izuzeta — niskorizična, imaju svoj uži
  prekidač (ADR-0099).

Uslovi su **I**, nikad „ili": živo okruženje **I** globalni prekidač **I**
(prazna lista ili poklapanje). Kill-switch, odobrenje, trust i AI-oznaka ostaju
nepromenjeni, pre ovoga.

## Bezbedno isporučeno
Prekidač je i dalje `false`, lista je prazna → `external_live` vraća isto što i
pre (ništa ne izlazi). Mašineriju gradimo, akciju NE palimo.

## Procedura za prvu pravu akciju (kad budemo spremni)
1. Postavi `EXTERNAL_ACTIONS_ALLOWLIST` na **tačno jedan** unos (npr.
   `P-00001|telegram:wk_ivana|channel.post.create`).
2. Prebaci TU personu u `CONTROLLED_LIVE`.
3. Tek onda `GLOBAL_EXTERNAL_ACTIONS_ENABLED=true`.
→ Izlazi isključivo ta jedna akcija; sve ostalo ostaje dry-run. Odobrenje po
akciji i dalje važi.

## Sledeće
- Pre-flight „da li bi ova objava izašla?" izveštaj (čita `external_live` + sve
  uslove, bez izvršenja) — vidljivost pre paljenja.
- Trust prag po tipu akcije kao dodatni uslov.
