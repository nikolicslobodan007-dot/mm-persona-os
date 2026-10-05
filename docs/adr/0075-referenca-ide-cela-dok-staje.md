# ADR-0075 — Referenca ide cela dok staje, izvod je izuzetak

- **Status:** prihvaćen (05.10.2026.)
- **Izvršilac:** Ines Babić P-00028 — namerno ne agent koji te brifove dobija
  za kodiranje tog modula.
- **Prethodi:** ADR-0041 (brif), ADR-0061 (zaštićena zona se čita), ADR-0068
  (referenca nosi i model, ne samo rečnik), ADR-0073 (brif nosi i ono što se
  čita), ADR-0033 (pravilo nula)
- **Menja:** `apps/orchestration/brif.py`
- **Canon:** §13

## Šta se desilo

Dva puta u dva dana referenca je stigla prazna.

**04.10.** Lazar je trebalo da napiše komandu `vestina` po uzoru na
`apps/content/recnik.py`. Izvod tog fajla je **29 B** — dva prazna zaglavlja
klasa, nijedan red funkcije `uvezi()` zbog koje je referenca i data.
Zaobišli smo tako što smo `recnik.py` stavili u **opseg zadatka**, pa je stigao
ceo — uz izričitu zabranu da ga agent menja.

**05.10.** Elena treba da napiše test za `apps/memory/vestine.py`. Izvod: **15 B**.
Jedan red: `class Vestina:`. Ovde zaobilaženje ne postoji — Elena ima
`code.write` samo nad `tests` i tako treba da ostane.

## Izmereno (04–05.10.)

| fajl | ceo | izvod | šta je izvod zadržao |
|---|---|---|---|
| `common/enums.py` | 41.552 B | 15.874 B | **sve članove** — radi kako treba |
| `apps/memory/models.py` | 19.368 B | 4.534 B | **sva polja** — radi kako treba |
| `apps/content/recnik.py` | 10.473 B | **29 B** | dva prazna zaglavlja |
| `apps/memory/vestine.py` | 3.189 B | **15 B** | jedno zaglavlje |

Razlika nije u veličini fajla nego u tome **gde mu je vrednost**: u imenima
(enum, model) ili u postupku (funkcija). `_CLAN` hvata dodele (`IME = ...`);
`@dataclass` sa anotacijama (`ime: str`) nema nijednu dodelu, pa izvod ostane
prazan. ADR-0068 je isti kvar rešio za mala imena polja; ovo je sloj ispod.

## Odluka

### 1. Referenca ispod praga ide cela

```
MAX_REFERENCA_CELA = 12_000  # B
```

Fajl manji od toga šalje se **neizmenjen**. Izvod se pravi samo za ono što je
preko praga.

Prag je izveden iz mere, ne iz osećaja: `enums.py` (41.552 B) je jedini
referentni fajl kome izvod zaista treba i ostaje iznad praga; `recnik.py`
(10.473 B) i `vestine.py` (3.189 B) prolaze celi. Najskuplji slučaj — referenca
od 12.000 B — je **6 % od `MAX_TOTAL_BYTES`**.

### 2. Plafon se ne diže

Referenca i dalje ulazi u isti `MAX_TOTAL_BYTES` kao fajlovi i ranija zakrpa
(ADR-0061). Ono što ne stane ide u `odsečeno`, kao i do sada. **Budžet koji ima
izuzetak nije budžet.**

### 3. Brif kaže u kom je obliku referenca poslata

Svaka referenca nosi `"skracen": true|false`. Pisac mora da zna da nije video
sve — isto pravilo kao `odsečeno` iz ADR-0041: *agent koji ne zna da mu nešto
fali piše zakrpu nad pretpostavkom.*

### 4. `_izvod` se ne dira

Radi tačno ono za šta je pisan i to radi dobro (dve gornje vrste u tabeli).
Menja se **kad se poziva**, ne šta radi.

## Šta je odbačeno

- **Da `_izvod` prepozna „vredan" fajl po sadržaju.** To je pogađanje čega ima
  u fajlu, a pogađanje je tačno ono od čega bežimo (ADR-0033).
- **Da se referenca stavlja u opseg zadatka**, kako smo zaobišli 04.10. Daje
  pravo **pisanja** nad onim što treba samo čitati — protivno ADR-0061, i radi
  samo kad agent slučajno ima dozvolu nad tom putanjom. Elena je nema.
- **Da prag bude veći, npr. 20.000 B.** Tada i `models.py` (19.368 B) ide ceo i
  troši 10 % plafona na ono što izvod daje u 2,3 %.

## Posledice

- `apps/orchestration/brif.py` — `_referenca()` bira oblik po veličini i upisuje
  `skracen`.
- `tests/test_brif.py` — provera da fajl ispod praga stiže ceo, da onaj iznad
  stiže kao izvod, i da `skracen` govori istinu. **Piše ih drugi agent**
  (`RAZ-TES`), ne onaj koji menja `brif.py`.
- **`apps/orchestration` nije zaštićena zona** (izmereno 05.10. komandom
  `poverenje --zone`), pa ovu izmenu sme da napiše agent. Zaštićeno je ono što
  agenta **ograničava**: politika, katalog sposobnosti, težine rizika, audit,
  enumi, ADR-ovi, `canon_lint`, `.env`, compose.
- Izvršilac neka **ne bude** agent kome se brifovi i prave za kodiranje tog
  istog modula. Nije pravilo nego opreznost: ko piše pravila o tome šta će
  videti, neka to ne bude isti onaj koji te brifove dobija svaki dan.

## Zapisano za ADR-0033

Dva puta sam dao referencu i oba puta je stigla prazna, a oba puta sam to
**izmerio pre nego što je agent potrošio pokušaj** — jednom komandom nad
`_izvod`. Da nisam, Elena bi dobila `class Vestina:` i jedino što bi mogla
pošteno da uradi jeste da vrati `NE MOGU`.

Pouka: **mehanizam koji skraćuje mora da kaže koliko je skratio.** Izvod koji od
3.189 B napravi 15 B nije skraćivanje nego brisanje, a brisanje bez prijave je
isto što i laž.
