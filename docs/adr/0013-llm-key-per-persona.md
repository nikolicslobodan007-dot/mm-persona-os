# ADR-0013 — Poseban ključ modela za svaku personu

- **Status:** prihvaćeno
- **Datum:** 22.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §2, §13, §17 · ADR-0009
- **Kod:** `apps/llm_gateway/gateway.py` (`persona_env_name`, `credential_ref`),
  `config/settings/base.py` (`LLM_REQUIRE_PERSONA_KEY`), `console/` (kartica
  „Ključ za model”), `tests/test_content.py`

## Kontekst

Do sada je postojao jedan zajednički Anthropic ključ (`ANTHROPIC_API_KEY`) za sve
persone. Za pilot sa više persona to nije dobro iz tri razloga:

- **Trošak:** Anthropic konzola pokazuje trošak po ključu, pa se sa zajedničkim
  ključem ne vidi koliko troši koja persona. Naša evidencija troškova po personi
  ostaje, a ključ po personi daje nezavisnu proveru.
- **Šteta od jednog problema:** ako jedna persona ima problem ili joj ključ procuri,
  gasi se samo njen ključ, a ostale persone rade dalje.
- **Rok i ograničenja:** svaki ključ može imati svoj rok isteka i svoj limit potrošnje.

Povod je bio 22.09.: zajednički ključ je prestao da važi (HTTP 401) i sve persone
bi istog trenutka prešle na šablon.

## Odluka

- Ključ jedne persone je u `.env.prod`, pod imenom
  `<zajednička promenljiva>_<public_id bez crte>`, na primer
  `ANTHROPIC_API_KEY_P00001` za P-00001.
- **Redosled:** ako persona ima svoj ključ, koristi njega. Ako ga nema, koristi
  zajednički. Ako je `LLM_REQUIRE_PERSONA_KEY=true`, persona bez svog ključa ne
  koristi zajednički, nego piše lokalnim šablonom (greška `NO_PERSONA_KEY`).
- **U bazi nema ni ključa ni imena promenljive.** Pravilo je u kodu, a ključ je
  samo u `.env.prod` (Canon §2, §17). Radi samo za `env:` reference.
- Razmaci na početku i kraju ključa se uklanjaju. Greška pri lepljenju u nano ne ruši poziv.
- Konzola na strani persone prikazuje za svaku uključenu spoljnu rutu da li
  persona koristi **svoj** ključ, **zajednički** ili **nema ključ** (piše šablonom),
  zajedno sa imenom promenljive. Sam ključ se nikad ne prikazuje.

## Postupak za novu personu

1. U Anthropic konzoli napravi ključ nazvan po personi (npr. `persona-os-P00002-ime`),
   sa najdužim rokom koji konzola nudi.
2. `nano .env.prod` → dodaj red `ANTHROPIC_API_KEY_P00002=...`.
3. `up -d --force-recreate web worker_core worker_channel worker_browser beat`.
4. U konzoli, na strani persone: „Ključ za model: svoj”.

## Posledice

- Kad sve persone dobiju svoj ključ, zajednički ključ se može ukloniti, a
  `LLM_REQUIRE_PERSONA_KEY=true` sprečava da nova persona slučajno troši tuđi ključ.
- Rok isteka ključa se ne vidi preko API-ja. Beleži se u „stanje rada” i
  obnavlja se ručno pre isteka.
- 388 testova (dodato 3).

## Dopuna 24.09. — ključ po agentu je pravilo, ne mogućnost

Prvi zadatak koji je Mila zadala Jovanu (P-00002) vratio se napisan **lokalnim
šablonom**: novi agent nema svoj ključ, a zajedničkog na serveru nema, pa je
gateway pao na rezervu.

Odluka: `LLM_REQUIRE_PERSONA_KEY=true` postaje podrazumevano stanje. Agent bez
svog ključa **ne pozajmljuje zajednički** — piše lokalnim šablonom, i to se
vidi u planu (`model: local/template-v1`, ADR-0024).

Razlog je isti kao i prvi put, samo sada za deset hiljada agenata: trošak se
meri po agentu, a ključ koji procuri gasi jednog agenta, ne celu firmu.

Zato `manage.py zaposli` na kraju ispisuje tačan red koji treba dodati u
`.env.prod` (`ANTHROPIC_API_KEY_P00002=…`), ili potvrdu da ključ već postoji.

