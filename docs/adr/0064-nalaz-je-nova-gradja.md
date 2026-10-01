# ADR-0064 — Nalaz posle merenja je nova građa, pa ponavljanje nije ponavljanje

- **Status:** prihvaćen (01.10.2026.)
- **Prethodi:** ADR-0044 (prekidač „nema napretka"), ADR-0062 (redosled kočnica),
  ADR-0045 (nalaz koji piše čovek), ADR-0041 §4 (brif nosi nalaze),
  ADR-0053 (čija je greška), ADR-0033 (pravilo nula)
- **Menja:** ADR-0044 §2 — prekidač „nema napretka" dobija uslov
- **Canon:** §6.4 (izvršni ugovor), §9.5 (poverenje)

## Šta se desilo

01.10.2026., `TSK-01M3V1NV6S82R25AMH8E6JWYNK` — prvi zadatak pisan sa
priručnikom (ADR-0060). Dva pokušaja, oba sa istim ishodom: `ruff`, `canon_lint`
i `migrations` zelene, `pytest` pao na `test_naslov_ulazi_u_budzet`.

Uzrok nije bio kod agenta. **Zadatak je bio nepotpuno postavljen:** tražio je da
`prompt_section` podigne `ValueError` na premalom budžetu, a nije rekao da
postojeći test brani staro ponašanje i mora da se izmeni u istoj zakrpi. Agent
je radio tačno po pravilu 6 priručnika („diraš samo ono što ti je traženo") i
nije mogao da prođe.

Kad je čovek to uočio i upisao nalaz (ADR-0045), sledeći pokušaj je odbijen:

```
ne piše se — nema napretka — dva puta zaredom padaju iste kapije: pytest
```

Prekidač je radio tačno kako je napisan — i time **zaključao agenta u trenutku
kad smo mu konačno rekli šta mu fali.** Jedini izlaz je bila ljudska zakrpa, a
ona iskrivljuje meru učinka (ADR-0042, ADR-0053): posao bi bio naš, a zadatak
njegov.

## Odluka

### 1. Prekidač meri mlevenje, a mlevenje traži istu građu

„Nema napretka" tvrdi: *agent ponavlja isti potez nad istim znanjem.* Druga
polovina te rečenice nikad nije bila proverena. Sad jeste:

```python
if len(pale) >= 2 and pale[-1] and pale[-1] == pale[-2] and not _novo_saznanje(zadatak):
```

`_novo_saznanje` je tačno kad postoji **otvoren** nalaz noviji od poslednjeg
ishoda kapije. Tada brif sledećeg pokušaja nosi nešto čega u prethodna dva nije
bilo (ADR-0041 §4), pa ponavljanje više nije ponavljanje.

Dva ograničenja, oba namerna:

| | zašto |
|---|---|
| samo **otvoren** nalaz | zatvoren nalaz je istorija, ne zadatak |
| samo **noviji od poslednjeg merenja** | stariji nalaz je agent već imao u brifu |

### 2. Prekidač se ne ukida, nego dobija uslov

Agent koji melje i dalje staje na drugom pokušaju. Razlika je u tome ko je kriv
za zastoj: dok god mu niko ništa novo nije rekao, zastoj je njegov. Čim mu čovek
kaže nešto novo, zastoj bi bio naš.

Ovo je u duhu ADR-0062: prva kočnica ostaje „nema napretka", ali ona sad meri
ono što je oduvek tvrdila da meri.

### 3. Otključava samo nalaz, ne i naše ćutanje

Nalaz je jedini kanal kojim čovek kaže izvršiocu šta fali, i jedini koji ulazi u
brif. Nema „otključaj zato što mislimo da će sad uspeti": ako nemamo šta da mu
kažemo, nemamo ni razlog da ga puštamo ponovo.

## Šta je odbačeno

- **Zastavica `--ignorisi-prekidac`.** Rešila bi večeras, a prekidač bi od toga
  postao predlog: prva ruka koja žuri ga isključi i niko ne sazna. Uslov koji
  stoji u kodu i ima proveru ne može da se „zaboravi".
- **Zatvoriti zadatak i otvoriti nov sa ispravljenom postavkom.** Prolazi kroz
  prekidač jer nov zadatak nema istoriju — i upravo zato je pogrešno: dva
  pokušaja i 12 centi bi nestali iz mere, a mera postoji da bi se videlo i ono
  što smo mi pokvarili (ADR-0053).
- **Ljudska zakrpa „samo ovaj put".** To je ADR-0050 ukratko: naša ruka upisana
  kao agentov rad.
- **Brojati i izmenu teksta zadatka kao novu građu.** `CodeTask.why` se danas ne
  menja komandom, a da se menja, tiha izmena postavke usred merenja bila bi gora
  od zastoja. Nalaz ostaje jedini put, jer ostavlja trag sa potpisom.

## Posledice

- `apps/orchestration/pisac.py` → `_novo_saznanje`, uslov u `zasto_ne`.
- `tests/test_pisac.py` → 3 nove provere i fikstura `drugi_agent`; ukupno **1142**.
- `TSK-01M3V1NV6S82R25AMH8E6JWYNK` nastavlja sa pokušajem 3 od 8, pošto nalaz
  `e139c3a8` stoji otvoren i noviji je od poslednjeg merenja.

## Zapisano za ADR-0033

**Prva:** prekidač je bio napisan iz ugla agenta koji greši, a ne iz ugla lanca u
kom i mi učestvujemo. „Dva puta isto" je tačna mera samo ako se ništa drugo nije
promenilo — a mi smo se promenili, time što smo mu konačno rekli šta fali.
**Kočnica koja ne gleda i našu stranu kažnjava agenta za naš tajming.**

**Druga:** ovo je četvrti put da sam zadatak postavio nepotpuno, i prvi put da je
to stajalo agenta dva pokušaja. Postavka je tražila novo ponašanje, a prećutala
staru proveru koja ga zabranjuje. **Zadatak koji menja ugovor mora da imenuje i
ono što se na taj ugovor oslanja** — inače agent bira između dva pravila iz
priručnika i oba poštovanja ga obaraju.

**Treća:** kvar se video tek kad je lanac prvi put prošao ceo, sa priručnikom, sa
nalazom i sa kočnicom u istom zadatku. Nijedan test ga ne bi otkrio, jer nijedan
nije spajao te tri stvari. **Rupa na spoju se vidi samo kad spoj stvarno nosi
teret.**
