# ADR-0029 — Computer Engine: agent za računarom

- **Status:** predložen (nije usvojen — ne piše se kod po njemu)
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0008 (runtime i adapteri), ADR-0002 (Aneks A)
- **Canon:** §12.1 (šta se ne automatizuje), §16.5 (audit), §21 (uslovi platformi)

## Kontekst

Cilj korporacije od prvog dana glasi: agenti koji su kao prave osobe i koji
umeju da pretražuju, kliknu, otvore program i provere rezultat — ali **ništa
zabranjeno i nikakvo zaobilaženje CAPTCHA**.

Prvi deo te rečenice danas nemamo. Agent ume da pozove API, da pročita javnu
stranicu i da napiše nacrt; ne ume da sedne za računar. Postoji gotov sloj koji
to rešava — [Cua](https://github.com/trycua/cua), MIT, driver za macOS, Windows
i Linux, sandbox lokalno ili u oblaku, ulaz preko MCP-a, CLI-ja i SDK-a, uz
benchmark deo za proveru da li je zadatak stvarno završen.

Ovaj ADR zapisuje **da je to odabran pravac** i **pod kojim uslovima** ulazi, da
se odluka ne bi donosila u hodu, pod pritiskom prvog zadatka koji je traži.

## Predlog

### 1. Merdevine ostaju, Computer Engine je poslednja prečka

```
1. API                      ← ako postoji sankcionisan put
2. kod / baza / CLI
3. Playwright (javni web)
4. Computer Engine          ← tek kad prve tri ne mogu
```

Redosled nije stvar ukusa. API poziv je brži, jeftiniji i determinističkiji od
agenta koji gleda ekran i pogađa dugme. Računar se uzima tamo gde danas rečenica
završava sa „ovo čovek mora ručno": desktop program bez API-ja, legacy ili GIS
alat, tabela koja se otvara u Excel-u.

### 2. Tabela platformi se **ne** menja

ADR-0008 t.1 kaže da nijedna društvena mreža nema browser put, i da lajk tuđe
objave, follow, prvi DM i komentar na tuđem sadržaju nemaju `ActionType`, jer
sankcionisan put ne postoji. **Computer Engine to ne menja.** Agent koji isto to
uradi mišem u virtuelnoj mašini nije rešio problem nego ga je sakrio: isto
kršenje uslova, samo bez traga u auditu.

Isto važi za javni web — `robots.txt`, jedan zahtev u sekundi po hostu, uslovni
GET, nikad prijava ni „prihvatam", CAPTCHA daje `NEEDS_HUMAN`. Desktop pregledač
koji ta pravila ne poštuje je korak unazad.

### 3. Sesija je akcija

Ovo je uslov bez kog se ne kreće, i glavni razlog zašto ADR stoji kao predlog.

Canon §16.5 traži pun trag `proposed → decision → attempt → outcome` za svaku
akciju, a `audit_completeness = 100%` je tvrdi KPI pilota. Sesija za računarom
je jedna neprozirna radnja sa dvesta klikova u sebi: ili svaki klik postaje
Action — što u obimu ne ide — ili sesija postaje crna kutija, što ruši KPI.

Predloženo rešenje: **sesija je jedna akcija sa unapred izjavljenim opsegom**.

- *proposed* — koji VM, koja aplikacija, koji domeni, koji nalog, koliko dugo,
  šta je očekivani ishod;
- *decision* — policy i odobrenje vezano za taj opseg, kao i za svaku drugu
  akciju, sa istim TTL-om;
- *attempt* — snimak rada (zapis klikova i unosa, snimci ekrana) kao
  `ActionAttempt.payload`, sanitizovan kao i svaki drugi payload;
- *outcome* — **verifikator**, ne izjava agenta. `expected == actual`, proverom
  koja ne zavisi od toga što agent tvrdi.

Taj poslednji red je zapravo najveća vrednost celog sloja. Danas naš
`content.draft` javi „gotovo" kad se korak izvršio, ne kad je rezultat tačan.

### 4. Izolacija i tajne

Nijedan agent ne dobija računar operatera. Jednokratna mašina, ograničen nalog,
ograničene tajne, posao, rezultat, gašenje.

Ali VM koji se negde prijavi drži **živu sesiju** — a to je tajna koja živi van
našeg modela (`credential_ref`, vrednost nikad u bazi, ADR-0013). Kako se ta
sesija zapisuje, ograničava i gasi je drugi uslov pre usvajanja; nije rešen.

### 5. Prva primena: noćni QA nad sopstvenom konzolom

Kad dođe red, ne kreće se od tuđih sistema nego od našeg: prijava u konzolu,
agent, nacrt, odobrenje, PDF, mobilni prikaz, snimak ekrana kod odstupanja.
Naš sistem, naš nalog, ničiji tuđi uslovi — i zadatak čiji se ishod meri, pa se
na njemu proverava i sam verifikator.

## Šta je odbačeno

- **VM po agentu.** Deset hiljada agenata nije deset hiljada mašina. Računar je
  deljiv resurs koji se uzima i vraća, kao i svaki drugi.
- **Computer Engine kao zamena za Playwright.** Ne zamenjuje ništa sa merdevina
  iznad sebe; dodaje se ispod njih.
- **Uvođenje pre GO odluke.** Posao pilota je da dokaže da agenti pišu i
  odgovaraju tačno. Računar u rukama agenta pre toga samo povećava površinu na
  kojoj stvari mogu tiho da pođu naopako.

## Otvoreno

- Pool Windows mašina je trošak i hardver — mesto mu je u sopstvenoj serverskoj
  sobi, ne na sadašnjoj Hetzner kutiji.
- Licence: jezgro je MIT, ali pojedini opcioni delovi imaju svoje (npr.
  `OmniParser` CC-BY-4.0, `ultralytics` AGPL-3.0). Proverava se po delu koji se
  stvarno uzima, pre nego što uđe u naš image.
- Usvajanje ovog ADR-a traži da uslovi iz t.3 i t.4 budu razrađeni do nivoa
  šeme, ne do nivoa namere.
