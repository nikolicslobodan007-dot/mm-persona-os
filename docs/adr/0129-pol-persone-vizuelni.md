# ADR-0129 — Rod sintetičke persone kao strukturno polje (VisualProfile.gender)

- **Status:** prihvaćen (07.11.2026.)
- **Povod:** 3D Virtual Office (ADR-0122, Mission Control) prikazuje svaku personu kao
  avatara. Dok postoji samo jedan (muški) placeholder, ženske persone (npr. Mila Vuković)
  izgledaju muško. Za izbor avatara po rodu treba strukturan podatak; rod do sada postoji
  samo kao slobodan tekst (`PersonaDossier.appearance_prompt`, počinje „Žena…"/„Muškarac…").
- **Prethodi:** ADR-0017 (dosije/izgled), ADR-0018 (izgled = sidro slike), ADR-0122
  (Persona OS je jezgro; Office čita read-only), Canon §9.4/§17 (persone su izmišljene,
  bez državnog identiteta).

## Uvid

Rod ovde NIJE podatak o stvarnoj osobi — persone su sintetičke i to nikad ne kriju. `gender`
je **vizuelni atribut** (kako avatar/slika izgledaju), pa pripada `VisualProfile`, ne dosijeu.
Dosije (`PersonaDossier`) ostaje interni i nikad se ne izlaže kroz Office bridge; samo se iz
njegovog teksta jednokratno izvede strukturan rod.

## Odluka

**1. Enum `Gender`** u `common/enums.py` (Canon §20 tačka 3): `FEMALE`, `MALE`, `UNSPECIFIED`.

**2. Polje `VisualProfile.gender`** (`CharField`, choices=Gender, default `UNSPECIFIED`,
blank). Migracija `visuals/0002`. `UNSPECIFIED` kad opis ne daje jasan rod.

**3. Backfill** `manage.py backfill_gender`: čita prvu reč `PersonaDossier.appearance_prompt`
(„Žena…"→FEMALE, „Muškarac…"→MALE), postavlja `VisualProfile.gender`. Idempotentno; `--dry-run`
i `--force`. Dosije se NE menja i NE izlaže.

**4. Izlaganje u Office API V1.2** — aditivno: `gender` u `AgentListItem` i `AgentDetail`
(`/agents`, `/agents/{public_id}`). Ugovor `office-v1.yaml` → **1.3.0** (novo opciono polje,
bez nove rute, bez promene postojećih). Ostaje read-only, allowlist, default-deny.

**5. 3D renderer bira avatara po `gender`** (žensko→ženski lik, inače muški/fallback) — zaseban
PR, uz ženski Mixamo lik.

## Posledice

- Mila i ostale ženske persone dobijaju ženski avatar; generator mase (10k) dobija jedno
  strukturno polje umesto parsiranja teksta.
- Office bridge i dalje ne izlaže dosije ni promptove — samo izvedeni `gender`.
- Dvosmisleni/prazni opisi → `UNSPECIFIED` → muški/fallback avatar dok se ručno ne ispravi.

## Sledeće

- PR-B: konverzija ženskog Mixamo lika → GLB + izbor avatara po rodu u rendereru.
- Seeder/generator (`ekipa`, masinerija) da postavlja `VisualProfile.gender` direktno pri
  kreiranju novih persona (da backfill ne treba ponavljati).
