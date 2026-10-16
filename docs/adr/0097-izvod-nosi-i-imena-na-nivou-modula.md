# ADR-0097 — Izvod nosi i imena na nivou modula

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Pisac je vratio prazno i pitao da li konstanta postoji. Postojala
  je, u `main`, od istog jutra — ali je izvod nije nosio. Izmereno 16.10.
- **Prethodi:** ADR-0061, ADR-0068, ADR-0080, ADR-0033
- **Menja:** `apps/orchestration/brif.py` — `_CLAN` / `_izvod`.
- **Canon:** §20

## Izmereno

Zadatak TSK-01M52A7H5H5DEQ6411XMDG6011 tražio je da `build()` koristi
`E.PROFILE_VESTINE_TOKENS[profile]`. Pisac je vratio `PRAZNA_ZAKRPA` i pitanje:
postoji li taj rečnik ili da koristi `PROFILE_MEMORY_TOKENS`. Oba postoje u
`common/enums.py`, koji je po ADR-0061 **uvek** u referenci.

Uzrok je jedan izraz u `apps/orchestration/brif.py`:

```python
_CLAN = re.compile(r"^    [A-Za-z_][A-Za-z0-9_]* = ")
```

Četiri razmaka na početku su obavezna. Sve što stoji uz levu ivicu fajla ne
ulazi u izvod.

Mereno nad tri fajla, 16.10.:

| Fajl | Hvata sada | Promašaj na nivou modula | Promašaj u klasi (anotirano) |
|---|---|---|---|
| `common/enums.py` | 443 | **43** | 0 |
| `apps/observability/models.py` | 61 | 0 | 0 |
| `apps/memory/models.py` | 88 | 0 | 0 |

Izvod `enums.py` ima 516 redova i u njima **nijedan** od četiri rečnika
`PROFILE_*`. Pisac nikada nije ni mogao da vidi `PROFILE_MEMORY_TOKENS` — ovo
je prvi put da je neki zadatak za njim posegao, pa se rupa pokazala tek sada.

Sumnja da se gube i anotirane dodele unutar klasa (`    polje: int = 5`)
proverena je i **nije se potvrdila**: nula promašaja u sva tri fajla. Zapisuje
se da se ne bi popravljalo ono što nije pokvareno.

## Odluka

`_izvod` hvata i dodele na nivou modula, uz postojeće zaglavlja klasa i dodele
unutar klasa.

Obrazloženje je isto ono iz ADR-0061 i ADR-0068: referenca postoji da bi pisac
znao **šta postoji**, i kad mu to ne kaže, on po ADR-0033 ispravno odbija da
pretpostavi — pa prolaz prođe bez ijednog reda koda. Rečnik sistema koji
prećuti četrdeset tri imena nije rečnik nego polovina rečnika.

Cena je merena, ne procenjena: 43 reda povrh 443, na izvodu od 15.874 B. To je
manje od jednog procenta plafona brifa.

## Šta se ovim NE menja

Dodele unutar klasa se hvataju kao i do sada; izraz za njih se ne dira, jer je
mereno da ništa ne propušta.

`_KLASA` i prag `MIN_IZVOD_PROCENAT` ostaju isti. Ovo nije promena politike
izvoda nego ispravka jednog izraza koji je pisan za enume pa je uvlaku primio
kao pravilo umesto kao slučajnost (isti oblik greške kao u ADR-0068, gde je
`_CLAN` hvatao samo VELIKA imena).

Spisak `REFERENCA` ostaje isti. Problem nije bio koji fajl ide piscu, nego
koliko od tog fajla stigne.
