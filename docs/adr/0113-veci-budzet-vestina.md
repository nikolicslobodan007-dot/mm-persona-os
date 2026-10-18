# ADR-0113 — Veći budžet veština za profile gde agent radi posao

- **Status:** prihvaćen (18.10.2026.)
- **Povod:** ADR-0112 je pokazao da u paket sada staje 12 veština umesto 4, i
  da ograničenje više nije rasipanje (pune korake na sve) nego **sam budžet**
  od 1000 tokena. Vlasnik, čiji je deklarisani prioritet sakupljanje veština,
  tražio je da agent nosi više.
- **Prethodi:** ADR-0096 (dva odvojena plafona: memorija i veštine),
  ADR-0112 (indeks + pune)
- **Menja:** `common/enums.py` (`PROFILE_VESTINE_TOKENS`)

## Odluka

Plafoni veština se dižu za profile u kojima agent **radi posao**, a ostaju
mali za reaktivne/introspektivne profile gde bi gomila veština bila šum:

| Profil | Pre | Posle |
|---|---|---|
| `reply_context` | 600 | 600 (nepromenjeno) |
| `daily_planner` | 1000 | **2000** |
| `content_creation` | 1000 | **2500** |
| `research` | 2000 | **3000** |
| `reflection` | 600 | 600 (nepromenjeno) |

## Zašto je ovo bezbedno

Veštine imaju **svoj** budžet, POVRH budžeta memorije (ADR-0096) — podizanje
ne krade prostor ličnom iskustvu persone. Jedino raste dužina prompta i cena;
vlasnik je rekao da cena nije presudna, a dobitak (agent zna svoj alat) je
veći od troška ispravljanja agenta koji ne zna.

## Granica

Brojke su i dalje postavljene rukom, ne izmerene do zasićenja. Kad se izmeri
koliko veština agent zaista koristi u odnosu na koliko ih nosi, ovo je prvo
mesto za ponovno podešavanje — naniže ako se pokaže da je gomila šum, naviše
ako nedostaje. Indeks (ADR-0112) i dalje hvata ostatak preko imena.
