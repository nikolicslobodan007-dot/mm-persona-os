# ADR-0080 — Izvod koji pojede fajl nije izvod

- **Status:** prihvaćen (12.10.2026.)
- **Povod:** 12.10. je Lazar (P-00027) odbio zadatak „Testovi za transkripciju"
  rečima da mu nedostaje sadržaj `apps/llm_gateway/gateway.py`. Izmereno posle
  odbijanja: od tog fajla je u brif stiglo **45 bajtova** od 16.857.
- **Prethodi:** ADR-0075 (referenca ide cela dok staje), ADR-0068 (referenca
  nosi i model), ADR-0061 (zaštićena zona se čita), ADR-0041 (pisac mora da zna
  da nije video ceo fajl), ADR-0033 (pravilo nula)
- **Menja:** `apps/orchestration/brif.py`, funkcija `_referenca` — izbor između
  celog teksta i izvoda. `_izvod` se **ne dira**.
- **Canon:** §7.3

## Šta se desilo

`_izvod` hvata zaglavlja klasa i dodele unutar klasa. Za rečnike (`enums.py`) i
Django modele to je tačno ono što treba. Za fajl koji je građen od **funkcija**
na nivou modula izvod ne hvata ništa — a ako u takvom fajlu postoji makar jedna
klasa, izvod nije prazan, pa ne pada ni u ono spasavanje iz ADR-0068 („fajl bez
ijedne klase vraća se ceo"). Dobije se najgori mogući ishod: fajl koji formalno
jeste poslat, a praktično nije.

ADR-0075 je ovu rupu već imenovao i zatvorio je **samo odozdo**: fajl ispod
`MAX_REFERENCA_CELA` (12.000 B) ide ceo. `gateway.py` ima 16.857 B i prošao je
pored te ograde.

## Izmereno pre pisanja (12.10.)

Izvod pokrenut nad svakim fajlom koji danas ide ili bi išao kao referenca:

| fajl | ceo | izvod | ostaje |
|---|---:|---:|---:|
| `common/enums.py` | 42.978 | 16.183 | 37,7 % |
| `apps/visuals/models.py` | 4.205 | 1.805 | 42,9 % |
| `apps/observability/models.py` | 11.699 | 3.426 | 29,3 % |
| `api/audit.py` | 3.006 | 3.006 | 100 % (nema klase) |
| `tests/conftest.py` | 4.180 | 4.180 | 100 % (nema klase) |
| `apps/orchestration/brif.py` | 16.475 | 16.475 | 100 % (nema klase) |
| **`tests/test_content.py`** | 19.539 | **128** | **0,7 %** |
| **`apps/llm_gateway/gateway.py`** | 16.857 | **45** | **0,3 %** |
| **`apps/memory/vestine.py`** | 3.493 | 15 | 0,4 % |
| **`apps/content/recnik.py`** | 10.779 | 29 | 0,3 % |
| **`apps/orchestration/zadaci.py`** | 22.031 | **28** | **0,1 %** |
| **`apps/policy/service.py`** | 38.289 | **46** | **0,1 %** |

Dva zaključka, oba iz tabele a ne iz glave:

1. Podela nije „klase protiv funkcija" nego **oštar rez**: ono što izvod opisuje
   dobro ostaje na 29–43 %, ono što uništava pada na 0,1–0,7 %. Između 0,7 % i
   29,3 % nema nijednog izmerenog fajla. Prag se zato sme postaviti, a ne
   pogoditi.
2. Pogođena su dva fajla koja su za ovaj sistem najvažnija: `zadaci.py` (28 B) i
   `policy/service.py` (46 B). Da smo ih ikada stavili u referencu, agent bi
   odbio zadatak, a mi bismo mesec dana tražili grešku u agentu.

## Odluka

U `_referenca` izbor postaje trostruk, umesto dvostruk:

1. fajl ispod `MAX_REFERENCA_CELA` → **ceo**, kao i do sada (ADR-0075);
2. fajl iznad praga čiji izvod zadržava **bar 25 %** teksta → **izvod**, kao i
   do sada (`enums.py`, modeli);
3. fajl iznad praga čiji izvod zadržava **manje od 25 %** → **ceo, dok staje u
   preostali `MAX_TOTAL_BYTES`**; ako ne staje, šalje se izvod i `skracen` ostaje
   `true`, jer ADR-0041 traži da pisac zna šta nije video.

Prag od 25 % je izabran tako da najgori fajl koji izvod opisuje dobro (29,3 %)
ostane na izvodu, a najbolji koji uništava (0,7 %) pređe na ceo tekst. Rez je
širok 28 procentnih poena i nijedan izmereni fajl ne leži u njemu.

`_izvod` se ne menja. On radi tačno ono za šta je pisan; greška je bila u tome
**kome se daje**.

## Šta ovo ne rešava

Fajl koji je i funkcijski i veći od preostalog budžeta i dalje stiže kao izvod
od 45 bajtova, samo sada uz pošten `skracen: true`. Prvi takav zadatak mora da
se podeli na manji opseg, ili da dobije izvod koji hvata i potpise funkcija.
Ne pišemo to danas jer takav fajl još nije stigao — a ADR-0033 zabranjuje da se
rešenje piše za pretpostavljen slučaj.

## Moja greška, po imenu

Brif za Lazara sam sastavio **znajući** da je `gateway.py` iznad praga, i odlučio
da to nadoknadim time što ću izmerene činjenice (potpis funkcije, atribute
`LLMError`, vrednost `LOCAL_PROVIDER`) prepisati u sam zadatak. Nije prošlo, i
nije trebalo da prođe: ADR-0033 agentu zabranjuje da pretpostavlja, a moja proza
o fajlu nije fajl. Agent je tražio da vidi kod i bio je u pravu.

Peti put u deset dana da zadatak pukne na istom mestu — na referenci koja je
nepotpuna — i prvi put da uzrok nije izbor fajlova nego mašina koja ih seče.
Cena odbijanja: 5 centi, jedan pokušaj od osam.
