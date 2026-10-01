# ADR-0066 — Rep hunka se dopunjuje iz fajla, jer model sam kaže koliko mu fali

- **Status:** prihvaćen (01.10.2026.)
- **Prethodi:** ADR-0065 (hunk mora da ima rep), ADR-0052 (zaglavlje se
  prebrojava), ADR-0049, ADR-0053 (čija je greška), ADR-0033 (pravilo nula)
- **Menja:** ADR-0065, odeljak „Šta je odbačeno" — prva stavka se **povlači**
- **Canon:** §6.4 (izvršni ugovor)

## Šta se desilo

ADR-0065 je uveden u podne. Posle njega, pokušaji 4 i 5 na
`TSK-01M3V1NV6S82R25AMH8E6JWYNK` odbijeni su **našom novom porukom**, koja je
agentu doslovno rekla šta da uradi:

> hunk u redu 29 se završava izmenjenim redom. `git apply` takav hunk odbija —
> dodaj bar 1 red konteksta iza poslednje izmene (red 194 fajla)

Poruka mu stiže u brif (ADR-0050), pravilo 2 priručnika je ispravljeno i upisano
(„izmenjeno 1"), a hunk je dva puta zaredom opet bio bez repa.

Provereno šta **nije** uzrok, pre nego što je išta zaključeno:

| sumnja | mera | ishod |
|---|---|---|
| odgovor je odsečen na granici tokena | `finish_reason` svih 6 poziva | `end_turn`, izlaz 771–1954 od 8000 |
| mi mu sečemo rep pri prebrojavanju | poslednji red sačuvane zakrpe | `+ assert …` — rep nikad nije ni stigao |
| poruka ne stiže do modela | `brif._prethodna` + `pisac._prompt` | stiže, u `ishod` |

Ostaje ono što se vidi u samom zaglavlju: model piše `@@ -186,10`, a u telu
ostavlja **osam** starih redova. **Sam je izbrojao da tamo idu još dva reda — i
nije ih otkucao.** Dva puta isto, istom greškom.

## Odluka

### 1. Manjak repa se dopunjuje doslovnim redovima iz fajla

`zakrpa.dopuni_rep` radi **pre** `prebroj_hunkove`: kad zaglavlje traži više
starih redova nego što ih telo daje, a telo se završava izmenom, razlika se
uzima iz fajla, sa pozicije koju je model deklarisao, i dopisuje kao kontekst.

Dokazano nad pravim `git`-om, nad pravim fajlom:

| zakrpa | `git apply --check` |
|---|---|
| sirova, kakvu model šalje | `corrupt patch` |
| ista, posle dopune | **prolazi** |

### 2. Zašto ovo nije pogađanje — i zašto ADR-0065 povlači svoju zabranu

U podne sam ovo odbacio rečenicom: „prvi put kad pogodimo pogrešan red dobijamo
zakrpu koja se primeni na pogrešno mesto i prođe kapije." Ta rečenica **ne
stoji**, i evo zašto:

- **Koliko** redova fali ne pogađamo — kaže model, svojim zaglavljem.
- **Koji** su to redovi ne pogađamo — kaže fajl, na poziciji koju je model
  deklarisao.
- Ako je pozicija pogrešna, `git` ni dalje neće naći vodeći kontekst i zakrpa
  pada — isto kao da dopune nema. Dopuna ne može tiho da promaši: ili se sve
  poklopi, ili pukne kao pre.

> **Ispravka, 01.10.2026. popodne (ADR-0067).** Druga i treća alineja ne stoje.
> Pozicija iz zaglavlja **jeste** bila pogrešna — telo je stajalo 15 redova niže
> — pa je dopuna dopisala red sa tuđeg mesta. Zakrpa jeste pukla, kao što je
> ovde predviđeno, ali je `reason` prijavio **uspešnu dopunu**: mera je lagala o
> svom postupku iako nije pogrešila o ishodu. Izmereno je i da `git` uopšte ne
> čita broj iz zaglavlja nego traži telo po sadržaju. Od ADR-0067, `usidri` radi
> pre dopune i dopuna više ne čita deklarisanu poziciju nego nađenu.

Razlika u odnosu na podne nije u rezonovanju nego u merenju: tada sam mislio da
rep fali slučajno, a izmereno je da fali **sistematski**, i da model uz manjak
sam prilaže i njegovu veličinu. Odluka doneta nad pogrešnom pretpostavkom se
menja kad pretpostavka padne — to je ADR-0033, ne nedoslednost.

### 3. Dopuna se uvek vidi

Ide u `reason` zakrpe, u `audit` i pred recenzenta, istom logikom kao
prebrojavanje zaglavlja (ADR-0052): **naša ruka u tuđem radu se ne krije.**
Recenzent po tome može da razdvoji šta je napisao agent, a šta smo dopisali mi.

### 4. Granica: najviše pet redova

`NAJVISE_DOPUNE = 5`. Manjak veći od toga nije zaboravljen rep nego nešto drugo
— pogrešna pozicija, prepisan fajl, zabuna o kom se mestu radi — i tada zakrpa
pada kao i pre (ADR-0065). Dopuna takođe staje na kraju fajla: zaglavlje koje
traži više redova nego što fajl ima se **ne izmišlja**.

## Šta je odbačeno

- **Dopuniti rep i kad zaglavlje ne traži više nego što telo daje.** Tada nemamo
  model koji nam kaže koliko fali, pa bismo zaista pogađali. Takav hunk i dalje
  pada po ADR-0065.
- **Dopisati samo jedan red, jer je toliko dovoljno `git`-u.** Zaglavlje kaže
  koliko ih fali; dopisati manje znači ostaviti brojeve netačnim i osloniti se na
  to da će ih `prebroj_hunkove` prepraviti. Jedna ruka u zakrpi je dovoljna.
- **Da ja napišem tu zakrpu umesto agenta.** Rešilo bi zadatak večeras i upropastilo
  jedini razlog zbog kog je rađen: merenje priručnika (ADR-0060 §6). Posao koji
  uradi čovek ne meri agenta.
- **Čekati da model nauči.** Pet pokušaja, 30 centi, dve izričite poruke. Pravilo
  koje agent ne može da ispuni je naš problem, ne njegov (ADR-0061).

## Posledice

- `apps/orchestration/zakrpa.py` → `dopuni_rep`, `NAJVISE_DOPUNE`, polje
  `Nalaz.dopune`, poziv u `check` **pre** `prebroj_hunkove`, upis u `reason` i
  `audit`.
- `tests/test_zakrpa.py` → 7 novih provera; ukupno **1154**.
- `TSK-01M3V1NV6S82R25AMH8E6JWYNK` — pet pokušaja i 30 centi otišlo je na naše
  kvarove; preostala su tri.

## Zapisano za ADR-0033

**Prva:** danas sam šest puta izneo uzrok i šest puta ga oborio merenjem —
mešani `diff --git`, razlika slike i repozitorijuma, kontekst bez razmaka,
Unicode, odsečen odgovor, i na kraju rep. Merenje je svaki put bilo jeftino
(jedna komanda), a tri od tih šest sam usput izgovorio naglas kao nalaz.
**Hipoteza izgovorena naglas se pamti kao nalaz** — pa se izgovara tek kad prođe
proveru.

**Druga:** ADR-0065 i ADR-0066 su razmaknuti dva sata i protivreče se u jednoj
stavci. To nije previd nego ispravan redosled: u podne nisam imao meru koja
pokazuje da model manjak **sam prijavljuje**. Odluka se menja kad padne
pretpostavka na kojoj je stajala, i tada se to piše naglas, a ne tiho ispravlja.

**Treća:** u testu koji sam prvi put napisao za ovu popravku stajalo je
`assert … or True`. To je provera koja ne može da padne — tačno ono što sam
30.09. prigovorio sopstvenom radu u `apps/behaviour`, i što ADR-0060 pravilom 13
traži od agenata. **Pravilo koje pišem drugima važi i za mene u istom fajlu.**
