# ADR-0070 — Upis rezultata je knjiženje, ne presuda

- **Status:** prihvaćen (02.10.2026.)
- **Prethodi:** ADR-0043 (rezultat ide u granu), ADR-0040 (kapije se mere po
  zakrpi), ADR-0064 (nalaz je nova građa), ADR-0038 §6, ADR-0033 (pravilo nula)
- **Menja:** `rezultat.zabelezi` — brana `OPEN_BLOCKERS` se **uklanja**; ostaje
  u `zadaci.finish`, gde je i bila pre ovog ADR-a
- **Canon:** §6.4, §16.5

## Šta se desilo

Osmi pokušaj na `TSK-01M3Y4Q9H1WK9M9WN7J5HZEDZE` prošao je sve četiri kapije.
Grana se nije otvorila. Izmereno, redom:

| mesto | šta radi |
|---|---|
| `runner.py:290` | `gurni(rad, grana, ocekivano)` — grana se **gura** |
| `runner.py:291` | `api("/tasks/{id}/result", …)` — tek onda se javlja aplikaciji |
| `rezultat.py:188` | aplikacija odbija upis: otvoren je BLOCKER |
| `runner.py:295` | poslušnik hvata grešku, zapisuje je u svoj dnevnik i ide dalje |

Dva BLOCKER nalaza bila su moja i bila su tačna — oba su opisivala kvarove koje
je osmi pokušaj baš ispravljao. Zaboravio sam da ih zatvorim pre nego što je
poslušnik stigao do kraja. To je uredan tok posla, ne greška u redosledu rada.

Posledica **nije** bila da grana ostane zatvorena. Bila je ovo:

| | vrednost |
|---|---|
| gde je grana na disku | `e98cd30` |
| šta `CodeTask.commit_sha` kaže | `2e36011` |
| koliko dugo | dok to neko slučajno ne primeti |

A `commit_sha` je tačno ono što aplikacija sledeći put šalje poslušniku kao
`branch_expected_sha` za `--force-with-lease` (`rezultat.priprema:147`). Dakle
sledeće guranje bi palo — i to sa porukom koja kaže da je granu neko dirao rukom.
Nije je dirao niko; aplikacija je sama sebi slagala gde je.

Popravljeno rukom istog dana: nalazi zatvoreni, pa `zabelezi` pozvan sa SHA-om
koji je pročitan sa same grane, ne prepisan.

## Odluka

### 1. `zabelezi` više ne odbija zbog otvorenog nalaza

Brana je uklonjena. Razlog nije popustljivost nego **redosled**: u trenutku kad
se ta provera izvršava, grana je **već pomerena**. Odbijanje ne vraća ništa — ono
samo uskraćuje bazi činjenicu koja se već dogodila na disku.

Provera koja ne može da spreči ono o čemu sudi nije brana nego rupa u knjigama.

### 2. Sud ostaje tamo gde još nešto menja

`zadaci.finish` i dalje odbija zatvaranje dok je ijedan BLOCKER otvoren
(`zadaci.py:503`). Tu je provera delotvorna, jer zatvaranje zadatka **jeste**
korak koji se tada ne desi. Ništa se u tom pravilu ne menja.

`rezultat.za_pregled` i dalje uz svaku granu ispisuje broj otvorenih blokada, pa
`manage.py grane` čoveku i dalje kaže da nad tom granom visi nalaz.

### 3. Šta i dalje ostaje brana u `zabelezi`

| provera | ostaje | zašto |
|---|---|---|
| kapije zelene nad **tom** zakrpom | **da** | poslušnik gura samo kad su zelene; ovo je odbrana od poslušnika koji laže |
| zakrpa pripada ovom zadatku | **da** | mehanička tačnost zapisa |
| SHA je 40 heksadecimalnih cifara | **da** | isto |
| ime grane je izvedeno iz zadatka | **da** | isto |
| zakrpa već ima **drugi** commit | **da** | dva ishoda za istu zakrpu su protivrečnost, ne zastarelost |
| otvoren BLOCKER | **ne** | sudi o nečemu što se već desilo |

Razlika je prosta: ostaje sve što pita **„da li je ovaj zapis tačan"**, odlazi
ono što pita „da li je ovaj posao dobar". Prvo je posao knjigovođe, drugo je
posao recenzenta i čoveka.

## Šta je odbačeno

- **Preokrenuti redosled u poslušniku: prvo `/result`, pa guranje.** Premešta
  razilaženje umesto da ga ukloni — tada baza tvrdi da grana ima commit koji na
  disku ne postoji, što je gore: `--force-with-lease` bi očekivao commit kog
  nema i guranje bi palo zauvek, a ne jednom.
- **Pustiti poslušnika da ponovi `/result` dok ne prođe.** Ponavljanje ne menja
  uzrok: nalaz zatvara čovek, a poslušnik bi se vrteo dok ga neko ne zatvori.
- **Ostaviti branu i naučiti me da nalaze zatvaram pre nego što poslušnik
  završi.** To je pravilo koje zavisi od toga da čovek stigne pre mašine. Takvo
  pravilo nije pravilo nego sreća.
- **Da `zabelezi` sam zatvara blokade koje je zakrpa ispravila.** Primamljivo i
  pogrešno: ko je ispravio nalaz procenjuje recenzent, ne upisnik. ADR-0064 to
  već kaže za suprotan smer.

## Posledice

- `apps/orchestration/rezultat.py` → brana `OPEN_BLOCKERS` uklonjena, na njenom
  mestu objašnjenje zašto; četvrto pravilo u dokumentaciji modula.
- `tests/test_rezultat.py` → `test_otvoren_blocker_zadrzava` zamenjen sa
  `test_otvoren_blocker_ne_zadrzava_upis_ali_zadrzava_zatvaranje`: ista
  postavka, ali sada traži da se upis desi **i** da `finish` i dalje odbije.
- Ukupno **1171** provera.
- `TSK-01M3Y4Q9H1WK9M9WN7J5HZEDZE` — zatvoren 02.10.2026, commit
  `e98cd30c8d046cba777dee4c4d973235c8894be3`, **osam pokušaja, 51 cent od 300**.
  Prvi zadatak koji je prešao ceo put: brif → zakrpa → kapije → recenzija →
  grana → ljudska ruka → produkcija.

## Zapisano za ADR-0033

**Prva:** ovu branu sam napisao u ADR-0043 i bio zadovoljan njome. Izgledala je
kao oprez. Nikad je nisam izvrtao u redosledu u kom se zaista izvršava — da
jesam, video bih da poslušnik gura dva reda iznad. **Provera se ne ocenjuje po
tome šta zabranjuje, nego po tome šta je u trenutku njenog izvršavanja još
moguće sprečiti.**

**Druga:** kvar se sastojao od dve ispravne stvari: nalaz je bio tačan i brana je
radila kako je napisana. Ništa nije puklo, ništa nije prijavljeno kao greška, a
baza je slagala. **Zbir dve ispravne odluke u pogrešnom redosledu je kvar koji
se ne javlja nikome.**

**Treća:** danas je ovo drugi put da nas je zaustavilo nešto što alat radi
drugačije nego što smo pretpostavili — ujutru `git fetch` koji tiho odbija
(ADR-0069), uveče naš sopstveni redosled poziva. Oba puta je merenje trajalo
jednu komandu, a pretpostavka je trajala danima. **Kad nešto ne radi, prvo
izmeri šta se zaista dešava, pa tek onda popravljaj ono što misliš da je uzrok.**
