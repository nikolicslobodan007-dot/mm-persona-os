# ADR-0079 — Tuđi kod ulazi kao izvor, i nikad ne postaje naš

- **Status:** prihvaćen (08.10.2026.)
- **Povod:** Slobodan, 07.10.: „Hoću da od sada **VADIMO sve što možemo sa
  GitHub-a**, i da implementiramo kod nas. Neću da pišemo kod beveze."
- **Prethodi:** ADR-0077 (korpus na prva vrata), ADR-0074 (dvoja vrata),
  ADR-0059 (licenca se ne pretpostavlja), ADR-0033 (pravilo nula)
- **Menja:** ništa u kodu danas; imenuje jednu rupu koja se popravlja pre prvog
  preuzetog reda
- **Canon:** §10.4, §10.5

## Šta se desilo

Pravilo je Slobodanovo i dobro je: ne pišemo iznova ono što je neko već rešio i
objavio. Naše je ono što je zaista naše — logika Persona OS-a, politika, audit,
persona. Parsere, klijente, formate i raspoređivače uzimamo gotove.

Ovaj ADR ne raspravlja pravilo. On mu daje postupak, jer „uzeti sa GitHub-a"
bez postupka posle šest meseci znači „ne znamo odakle je ovo i pod čim stoji".

## Izmereno pre pisanja (08.10.)

| pitanje | izmereno |
|---|---|
| koje kutije licence postoje | `SLOBODNA`, `ZARAZNA`, `ZABRANJENA`, `NEPOZNATA` |
| koja je upotrebljiva | `LICENSE_BOXES_USABLE = frozenset({SLOBODNA})` |
| **ko čita tu listu** | **niko** — jedini pogodak van `enums.py` je test koji proverava da joj je vrednost tačna |
| ko čita `license_box` | `vestina.py` i `console/views.py` ga **upisuju**; baza ga proverava samo za `SLOBODNA` bez naziva; **nijedna provera pred upotrebu** |
| šta stoji u bazi | `Pravilo nula` → `SLOBODNA`; **`Rečnik uz Pravopis` → `NEPOZNATA`, naziv licence prazan**, 8.797 činjenica |
| sme li se preuzimati automatski | **ne** — `GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`, odlazak na GitHub su druga vrata (ADR-0074 §2) |
| nosimo li commit i putanju fajla | **ne** — ta polja ne postoje (ADR-0077 §3) |

## Odluka

### 1. Prvo se traži, pa se piše

Pre nego što se otvori zadatak koji nešto gradi, pitanje je: **postoji li već
slobodno rešenje?** Ako postoji i licenca je čista, uzima se. Ako ne postoji,
piše se naše — i to se u zadatku kaže naglas, da se zna da je traženo.

Ovo menja oblik zadatka, ne samo količinu koda: naš posao postaje spajanje i
naša logika, a ne iznova izmišljena osnova.

### 2. Kutija licence odlučuje, i to pre koda

- **`SLOBODNA`** (MIT, Apache-2.0, BSD i slično) — ulazi, uz obavezno zadržano
  ime autora i tekst licence.
- **`ZARAZNA`** (GPL, AGPL i slično) — **odbija se.** Ne zato što je loša, nego
  zato što bi povukla ceo naš sistem pod istu licencu. To je odluka o firmi, ne
  o fajlu.
- **`ZABRANJENA`** — ne ulazi.
- **`NEPOZNATA`** — ne ulazi. „Nema licence" znači „nema dozvole", ne „slobodno
  je" (ADR-0059 §2).

Licenca se **čita iz samog repozitorijuma** (LICENSE fajl, zaglavlja), ne iz
opisa, ne iz tuđeg teksta o tom repozitorijumu, i ne iz sećanja.

### 3. Lista upotrebljivih kutija mora da postane provera

`LICENSE_BOXES_USABLE` danas ne čita nijedan red koda. To je pravilo koje
postoji kao beleška, a beleška koju niko ne čita nije brava — isti kvar kao
`ingested_at` koji niko nije upisivao (ADR-0076).

**Dok ta provera ne postoji, nijedan preuzeti kod ne ulazi.** Zadatak koji je
uvodi ide **pre** prvog preuzimanja, ne posle.

### 4. Preuzimanje ide na prva vrata, kao i znanje

Agent ne odlazi na GitHub. Materijal donosi čovek, isto kao veštine (ADR-0077
§1). Kad GO odluka padne i druga vrata se otvore, ovaj ADR se dopunjuje — do
tada se ne pretvara da su otvorena.

### 5. Zavisnost pre kopije

Kad god postoji kao biblioteka, uzima se **kao zavisnost** — zapisana u
`pyproject.toml`, nadograđuje se, i ne stoji u našem repozitorijumu.

Kopiranje izvornog koda u naš repozitorijum je izuzetak: samo kad biblioteke
nema, kad je prevelika za ono što nam treba, ili kad je moramo menjati. Tada
ide u jasno označen folder, sa netaknutim LICENSE fajlom i zapisanom adresom i
commit-om odakle je uzeto.

### 6. Tuđe ime ostaje uz tuđi rad

Zaglavlja sa imenom autora i licencom se **ne brišu**. Ništa preuzeto se ne
objavljuje kao naše. To je Slobodanovo pravilo i stoji iznad svake udobnosti:

> „Nikada neću da nečiju knjigu objavim kao svoju. Niti da nečije ime
> zloupotrebljavam."

## Šta je odbačeno

- **Automatsko preuzimanje sa GitHub-a.** Druga vrata, čeka GO.
- **Da se `ZARAZNA` uzme „samo za ovaj deo".** Zaraznost se ne deli na delove;
  to je i razlog imena kutije.
- **Prepisivanje tuđeg koda „svojim rečima" da se izbegne licenca.** To nije
  pisanje svog koda nego pranje tuđeg, i ovde se ne radi.
- **Kopiranje u repozitorijum kao podrazumevano.** Zavisnost je podrazumevano,
  kopija je izuzetak sa razlogom.
- **Da ovaj ADR sam popravi `LICENSE_BOXES_USABLE`.** On imenuje rupu; popravku
  nosi zadatak, sa svojim merenjem i svojim testovima.

## Posledice

- **Pre prvog preuzetog koda** ide zadatak koji `LICENSE_BOXES_USABLE` pretvara
  u stvarnu proveru pred upotrebom znanja i koda.
- **Rečnik stoji kao `NEPOZNATA`, sa 8.797 činjenica.** Po ovom i po ADR-0059
  to znači „nema dozvole", a ništa ga danas ne zaustavlja jer provere nema.
  Treba izmeriti pod čim zaista stoji materijal Matice srpske i upisati tačnu
  kutiju — ili ga povući. Ovo nije pravni savet i ja nisam pravnik; ovo je
  nalaz da polje kaže jedno a upotreba radi drugo.
- Polja `commit` i putanja fajla iz ADR-0077 §3 postaju obavezna čim prvi
  preuzeti kod ili korpus uđe — bez njih „uzeto sa GitHub-a" nije sledivo.
- Zadaci koji grade nešto novo od sada u obrazloženju nose i rečenicu o tome
  da li postoji gotovo slobodno rešenje i zašto ga (ne) uzimamo.

## Zapisano za ADR-0033

Pre pisanja sam pretpostavio da kutija licence već negde koči upotrebu — jer
zašto bi inače postojala lista „upotrebljivih". Pretraga je pokazala da je
jedini čitalac te liste **test koji joj proverava vrednost**. Pravilo je bilo
zapisano i nikad sprovedeno, i to je drugi put u tri dana da nađem polje koje
postoji, ima smisla, a niko ga ne pita ništa.

Pouka je uža nego „proveri": **kad nađem pravilo zapisano u kodu, pitanje nije
da li je tačno, nego ko ga poziva.**
