# ADR-0144 — Petlja ispravke: šefova primedba se vraća piscu na jednu ispravku

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Nalaz 11.11. (plafon kvaliteta): recenzent (ADR-0108) radi odlično i
  odbija nacrt sa KONKRETNOM, izvodljivom kritikom — ali se ta kritika bacala.
  Nije bilo petlje „vrati piscu da ispravi"; posao bi samo stao („nije urađeno").
  Čovek-urednik bi rekao „izbaci X i Y", pisac bi sredio u jednom prolazu.
- **Prethodi:** ADR-0108 (recenzija pre vraćanja), ADR-0024 (content.draft/review),
  ADR-0110 (ishod lanca).
- **Menja:** `apps/content/service.py` (nova `revise()` + revizijski prompt u
  `draft`), `apps/content/steps.py` (`content.review` radi jednu ispravku),
  `apps/orchestration/razgovor.py` (`_ishod` vadi revidiran nacrt), testovi.

## Odluka
Petlja ispravke živi **unutar `content.review` koraka** — statični motor plana
se ne dira. Kad šef odbije sa **zanatskom** primedbom (ne „pitanje vlasniku",
ADR-0111):

1. **Izvršilac (autor nacrta) revidira** — `service.revise(pisac, original,
   primedba, …)` napravi ispravljenu verziju kroz iste kapije (disclosure,
   pravopis, tvrde zabrane). Prompt je „ispravi tačno ono na šta primedba
   ukazuje, zadrži dobro" umesto „napiši novo".
2. **Šef ponovo pregleda** revidiran nacrt.
3. Prođe → korak je gotov, revidiran nacrt je konačan (`revidiran: true`).
   I dalje pada → „nije urađeno" sa **finalnom** primedbom.

**Ograničeno na jednu ispravku** (1 retry) — da se ne vrti ukrug; standard se ne
spušta. Uloge se čuvaju: izvršilac piše i revidira, šef sudi.

Provera ponavljanja (`_repetition`) se za reviziju **preskače** — revizija
namerno liči na original, pa bi je dedup inače oborio kao duplikat.

## Posledice
- Precizna odbijanja (npr. „izbaci EU AI Act atribuciju i potpis") se pretvaraju
  u prolazne nacrte, bez spuštanja standarda.
- Trošak: do dva dodatna poziva modelu po odbijenom nacrtu (revizija + ponovni
  pregled). Ograničeno na jednom.

## Granice (za kasnije)
- Jedan retry je namerno; ako se pokaže da dva prolaza pomažu, broj je lako
  podesiti na jednom mestu.
- Na konačnom padu, prikaz „nacrt koji nije prošao" i dalje vadi originalni
  nacrt iz `content.draft` (ne revidiran) — dovoljno, jer je primedba glavna.
