# ADR-0037 — Šta radno mesto traži i ko sme da da poverenje

- **Status:** prihvaćen (25.09.2026.)
- **Prethodi:** ADR-0017 (radno mesto nije dozvola), ADR-0023 (zapošljavanje),
  ADR-0034 (opseg u poverenju), ADR-0035 (model zadatka)
- **Canon:** §3.11 (poverenje po capability-ju), §15.2 (klase odobrenja), §16.5 (audit)

## Problem

Firma ima 33 agenta na 26 radnih mesta i **nijedan nema nijednu dozvolu**. To nije
propust nego posledica ispravne odluke: radno mesto nije dozvola (ADR-0017). Ali
posledica te odluke je da poverenje mora nešto drugo da daje, a danas ga daje samo
čovek, komandom, jednom agentu, za jedan capability. Na 10.000 agenata to nije
postupak nego zanimanje.

Drugi problem je tiši i gori. Kad poverenje jednom počnu da dele šefovi-agenti,
ništa ne sprečava šefa da podređenom — ili sebi — da nivo koji sam nema. Tada
poverenje prestaje da bude lanac i postaje prsten.

## Odluka

### 1. Radno mesto opisuje šta traži, i ništa ne otvara

`Position.needs` je spisak onoga bez čega se posao ne može raditi: capability, nivo,
i opseg gde opseg ima smisla. Referent prodaje traži `email.reply_inbound@L2`;
programer traži `code.write@L1` u svom delu koda.

**Ovo nije dozvola i nijedan deo sistema ga ne čita kao dozvolu.** Motor pravila i
dalje gleda isključivo `TrustState`. `needs` je opis posla — ono što se traži da bi
se posao radio, a ne ono što je dato. Agent premešten na radno mesto ne dobija ništa
(ADR-0017 ostaje netaknut).

Korist je što se sada može postaviti pitanje koje se ranije nije moglo: **šta ovom
agentu nedostaje da bi radio posao za koji je zaposlen.**

### 2. Manjak se meri, ne pamti

`manage.py poverenje --manjak` poredi ono što mesto traži sa onim što agent ima i
ispisuje razliku — po agentu, po mestu ili po sektoru. Ništa ne menja.

### 3. Dodela po mestu je jedan potez, ali mnogo zapisa

`--po-mestu RAZ-PRO --razlog "…"` daje **tačno manjak**, svakom agentu na tom mestu.
U auditu ostaje **jedan red po agentu**, kao da je svaki dat rukom — jer i jeste,
samo se jednom kucalo. Ne daje se ništa iznad onoga što mesto traži: „kad sam već
tu, daću mu L2" nije poslovna odluka nego navika.

### 4. Niko ne daje ono što sam nema

Ovo je pravi razlog za ovaj ADR.

Kad poverenje daje agent (`agent:P-000xx`), gornja granica onoga što sme da da je
**njegov sopstveni nivo za taj capability na tom opsegu**. Šef sa `L1` ne pravi
podređenog sa `L2`, niti sebi diže nivo preko sebe.

Čovek (`user:…`) je koren: samo tu poverenje ulazi u sistem. Zato je i jedini koji
može da ga podigne prvi put, i zato svaki lanac poverenja, koliko god bio dubok,
završava na čoveku koji je za njega odgovoran.

Svi ostali oblici pozivaoca ostaju kako su bili. Ovo je svesno uže od „proveri
svakog": danas poverenje dodeljuju samo čovek i sistemski pozivi, a jedina rupa koju
treba zatvoriti pre nego što šefovi-agenti prorade jeste agent koji podiže sebe ili
svog podređenog. Stroža provera oblika pozivaoca dira model prijave na API-ju i ide
zasebno.

### 5. Zaštićene zone se ne otvaraju ni ovuda

`needs` koji bi tražio zaštićenu zonu se odbija pri dodeli, kao i svaka druga dodela
(ADR-0034 §5.1). Radno mesto ne može da postane zaobilaznica.

## Šta je odbačeno

- **Poverenje pri zapošljavanju.** Time bi radno mesto postalo dozvola, a ADR-0017
  bi postao ukras.
- **Da motor pravila čita `needs`.** Jedan izvor istine za odluku, i to je
  `TrustState`.
- **Dodela iznad onoga što mesto traži**, u istom potezu. Ako posao stvarno traži
  više, menja se opis mesta — i to se vidi.
- **Automatsko oduzimanje poverenja pri premeštaju.** Zvuči uredno, ali tiho gasi
  agenta usred posla. Manjak se vidi u `--manjak`; oduzimanje je zaseban, izričit
  potez.

## Posledice

- `Position.needs` + migracija; `POSITION_NEEDS` u `seed_org` kao izvor.
- `apps/personas/ovlascenja.py` — šta mesto traži i šta agentu nedostaje.
- `apps/policy/service.py` dobija granicu davaoca. To je zaštićena zona i menja se
  ovim ADR-om i ljudskom rukom — kako i piše u ADR-0034.
- `manage.py poverenje --manjak | --po-mestu`.
- Sledeće, odvojeno: ko sme da bude davalac (koja uloga), i da li šef-agent uopšte
  dobija to pravo pre nego što se izmeri njegov rad.
