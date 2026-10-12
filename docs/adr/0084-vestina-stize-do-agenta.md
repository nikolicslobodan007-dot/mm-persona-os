# ADR-0084 — Veština stiže do agenta, ili je nije bilo

- **Status:** prihvaćen (12.10.2026.)
- **Povod:** Izmereno 12.10.: u bazi stoji **jedna** veština, a nijedan agent je
  nikada nije video. Put od znanja do agenta ne postoji.
- **Prethodi:** ADR-0074 (dvoja vrata, veština ulazi od čoveka), ADR-0079
  (licenca odlučuje pre koda), ADR-0077 (bez populacije nema pravila izbora),
  ADR-0041 (brif i njegov plafon), ADR-0033 (pravilo nula)
- **Menja:** `apps/orchestration/brif.py` — nov ključ u brifu.
- **Canon:** §9.2, §10.5

## Šta je izmereno

| pitanje | nalaz |
|---|---|
| veština u bazi | **1** — „Pretpostavka je majka svih zajeba" |
| izvor | *Pravilo nula (ADR-0033)*, kutija **SLOBODNA**, „Sopstveni rad Web Korporacije" |
| ko upisuje | `apps/memory/vestine.py` i komanda `vestina` |
| ko čita | **niko** — jedini pogodak van uvoza je komentar u `brif.py` |
| ko čita `LICENSE_BOXES_USABLE` | **niko** — samo jedan test koji proverava vrednost (ADR-0079 §3) |

Dakle problem nije gomila neiskorišćenog znanja nego to što izlaza nema, pa
sakupljanje nema smisla. Ulaz je dokazan jednom veštinom; izlaz ne postoji.

## Odluka

Brif dobija ključ `skills`. U njega ulaze `KnowledgeFact` zapisi sa predikatom
`vestina.postupak`, i to **samo oni čiji izvor ima kutiju licence iz
`LICENSE_BOXES_USABLE`**. Uz svaku veštinu ide navođenje izvora — naslov i
naziv licence — jer znanje bez porekla nije znanje nego glasina (ADR-0079).

Veštine ulaze u **isti plafon** `MAX_TOTAL_BYTES` kao referenca, priručnik i
ranija zakrpa, i to **pre** fajlova koji se menjaju. Ono što ne stane ne nestaje
tiho nego ide u `truncated`, kao i sve ostalo (ADR-0041 §1).

## Čega namerno NEMA

**Nema pravila izbora.** Ne bira se koja veština ide kom agentu, nema bodovanja,
nema poklapanja sa putanjama zadatka. Populacija je **jedan**, a pravilo
napisano nad populacijom od jedan nije pravilo nego pretpostavka — isti razlog
iz kog je ADR-0077 odbio Opportunity Score dok nema šta da se meri.

Kad veština bude dovoljno da se obrazac vidi, pravilo izbora se piše **po
merenju**, svojim ADR-om, i tek tada.

## Zašto baš sad, sa jednom veštinom

Zato što je redosled bitan: dok izlaz ne radi, svako sakupljanje je ulaganje u
nešto što se ne koristi. Jedna veština je dovoljna da se put dokaže od kraja do
kraja — a kad put postoji, sakupljanje postaje posao sa ishodom.

Prva veština koju sistem ikada šalje agentu je, slučajno ali prikladno, pravilo
nula: *pretpostavka je majka svih zajeba*. Isto ono zbog kog je 12.10. agent
odbio zadatak umesto da izmisli sadržaj fajla koji nije video.

## Rupa koja ostaje imenovana

Komanda `vestina` ume samo uvoz — nema `--spisak`. Da bi čovek video šta je u
bazi, mora da otvori `shell`. To nije deo ove odluke, ali se zapisuje da se ne
bi zaboravilo.
