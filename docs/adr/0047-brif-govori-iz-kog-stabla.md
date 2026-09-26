# ADR-0047 — Brif govori iz kog stabla gleda

- **Status:** prihvaćen (26.09.2026.)
- **Prethodi:** ADR-0041 (brif), ADR-0043 (rezultat u granu), ADR-0044 (pisac),
  ADR-0045 (nalaz), ADR-0033 (pravilo nula)

## Problem

Prva popravka po recenziji nikad nije puštena — zaustavljena je pre poziva
modelu, jer bi brif bio **protivrečan**.

Lanac je do sada radio u jednom smeru: zadatak → zakrpa → kapije → grana. Grana
sa radom agenta **ne ide u `main`** dok ne prođe ljudsku ruku (ADR-0038 §6), a
posebno ne dok na njoj stoji `BLOCKER`. Slika aplikacije se gradi iz `main`.

`brif.build` čita fajlove sa diska te slike. Znači da bi Lazar, na drugom
pokušaju, dobio:

- `apps/content/lessons.py` **bez** svoje izmene — jer je ona samo na grani;
- dva nalaza koja opisuju kako ta izmena tiho seče spisak pouka.

Nalaz o kodu kog u priloženim fajlovima nema. Model bi pisao nad opisom koji se
ne poklapa sa onim što vidi — a to je tačno greška zbog koje `BLOCKER` i postoji.

Uzrok je zapisan još u ADR-0041 §2: **aplikacija nema `.git`.** Zna svoj disk, ne
zna granu. Do sada to nije smetalo jer druge iteracije nije bilo.

## Odluka

### 1. Brif kaže iz kog stabla su fajlovi

Polje `files_from` stoji uz svaki brif i kaže doslovno: fajlovi su trenutno
stanje glavne grane, rad sa grana zadataka u njima **nije**, i nova zakrpa se
piše nad ovim fajlovima.

Ranije se to podrazumevalo. Podrazumevano je pretpostavka koju niko nije proverio
(ADR-0033).

### 2. Brif nosi ranije predatu zakrpu

`previous_patch` je **poslednja zakrpa koja je već gledana** — ona koja ima
ishod kapija ili upisan commit. Nalazi i pale kapije govore o njoj, pa ide uz
njih. Pisac tada ima sve troje: trenutno stanje, svoju izmenu, i prigovor na nju.

Nemerena zakrpa se ne šalje: o njoj još niko nije rekao ništa, pa nema šta da se
popravlja.

`git` i dalje nije potreban — zakrpa je u bazi (ADR-0038 §3), a ne na grani.

### 3. Zakrpa troši isti plafon

Ranija zakrpa ulazi u istih 200 KB (ADR-0041 §1), a ne pored njih. Kad zbog nje
fajl ispadne, `truncated` kaže i to — **„deo zauzela ranija zakrpa"**. Plafon se
ne podiže tiho, jer bi to bilo isto ćutanje zbog kog je nastao prvi `BLOCKER`.

Sama zakrpa se seče na 20 KB, i onda `truncated` na njoj stoji `true`.

## Šta je odbačeno

- **Čitanje grane iz aplikacije.** Tražilo bi `.git` u slici ili git-klijent u
  `web`-u. Aplikacija nema posla sa repozitorijumom; to je posao poslušnika
  (ADR-0038 §2).
- **Spajanje grane u `main` da bi brif bio tačan.** Na grani stoji `BLOCKER`.
  Spojiti je da bi opis bio tačan znači ugasiti kapiju da bi izveštaj bio lep.
- **Da poslušnik pravi brif.** Tada bi granice iz ADR-0041 izašle iz aplikacije,
  a poslušnik bi morao da zna šta je zaštićena zona.
- **Slanje svih ranijih zakrpa.** Recenzija govori o poslednjoj; ostale su
  istorija i stoje u bazi.

## Posledice

- `brif.previous_patch`, `brif.files_from`, `brif.MAX_PATCH_BYTES`; prompt pisca
  ih izričito imenuje i kaže da se nalazi odnose na zakrpu, ne na fajlove.
- `tests/test_brif.py`: 8 novih provera. Ugovor regenerisan. Nema migracije.
- Drugi pokušaj po recenziji sada može da se pusti bez laži u promptu.

## Zapisano za ADR-0033

Ovo nije našla nijedna kapija. Našlo se tako što sam pre puštanja pitao **šta
će model tačno videti**, umesto da pretpostavim da brif nosi ono što bih ja
očekivao da nosi. Šest centi je mala cena, ali greška ne bi bila u ceni nego u
zaključku: merili bismo „ume li da popravi po recenziji", a merili bismo pisanje
ispočetka nad pogrešnim opisom.
