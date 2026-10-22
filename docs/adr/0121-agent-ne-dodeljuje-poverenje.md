# ADR-0121 — Agent (za sada) ne dodeljuje poverenje

- **Status:** prihvaćen (22.10.2026.)
- **Povod:** ADR-0037 §4 uveo je pravilo „niko ne daje ono što sam nema" — kad
  poverenje daje agent, granica je njegov sopstveni nivo. Pravilo je tačno, ali
  pretpostavlja da agenti već smeju da budu davaoci poverenja. Rad agenata još
  nije izmeren do nivoa na kom bismo im poverili širenje ovlašćenja na druge.
- **Prethodi:** ADR-0037 (šta radno mesto traži i ko sme da da poverenje),
  ADR-0033 (pretpostavka je majka svih zajeba — meri, ne pretpostavljaj),
  ADR-0034 (zaštićene zone)
- **Menja:** `apps/policy/service.py` (funkcija `granting_ceiling`),
  `tests/test_ovlascenja.py`. Bez migracija, bez promene modela, bez diranja
  `change_trust` logike oko `_set_trust`.

## Odluka

**1. Agent ne dodeljuje poverenje.** Dok se rad agenata ne izmeri, `agent:`
pozivalac ne može da provuče `change_trust` — podiže se `AGENT_GRANTING_DISABLED`.
Ne menja se ništa oko toga šta agent sme da *radi* sa poverenjem koje mu je čovek
dao; oduzima mu se samo moć da to poverenje *prosleđuje* drugome.

**2. Čovek ostaje koren, nepromenjeno.** `user:`, `service:` i `system:`
pozivaoci prolaze kao i do sada (`granting_ceiling` vraća `None` — bez granice do
najvišeg dodeljivog nivoa). Jedini davalac poverenja u sistemu je čovek.

**3. Provera postojanja ostaje.** Ako `agent:` pozivalac imenuje personu koja ne
postoji, i dalje se prvo podiže `UNKNOWN_GRANTOR` (nepoznat davalac se ne
prećutkuje); tek za postojećeg agenta važi zabrana.

**4. Ovo je prvi korak (B1).** Sledeći korak (B2, kad se sredi conftest i nalog
na produkciji): suziti i ljudsku granu na „samo `system_admin`" umesto bilo kog
`user:`. Za sada `user:` ostaje bez granice jer je jedini nalog koji dodeljuje
Slobodanov.

## Mera / uslov za povratak

Zabrana se skida tek kad se rad agenata izmeri do nivoa na kom je bezbedno da
agent bude davalac (zlatni skup / metrika koja se tek definiše). Dotle: agent
radi, čovek dodeljuje.

## Posledice

- **Pozitivno:** najosetljivija operacija — širenje ovlašćenja — ostaje u
  ljudskim rukama; površina rizika je uža.
- **Cena:** agent ne može autonomno da opremi podređenog; svaka dodela ide preko
  čoveka. Prihvatljivo u ovoj fazi (`GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`).
- **Izmereno (ADR-0033):** nijedan prod tok trenutno ne dodeljuje poverenje
  `agent:` akterom — `apps/content/steps.py` i `apps/orchestration/plans.py`
  koriste `agent:` samo kao audit-aktera (pravljenje dokumenta, delegiranje),
  ne za `change_trust`; komanda `poverenje` i API idu `user:` akterom. Zabrana
  zatvara vrata kroz koja danas niko ne prolazi.
