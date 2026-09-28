# ADR-0053 — Odbijena zakrpa nosi čija je greška

- **Status:** prihvaćen (28.09.2026.)
- **Prethodi:** ADR-0042 (merenje), ADR-0048, ADR-0050, ADR-0052, ADR-0034 §6, ADR-0033
- **Menja:** ADR-0042 — `ucinak` više ne broji odbijanja bez pitanja o uzroku

## Šta se desilo

Posle tri dana rada na programerskom departmanu, `ucinak` je za P-00027 pokazivao:

```
ZAKRPE 10   GRANA 2   ODBIJ. 6
```

Od tih šest odbijanja, **tri nisu bila njegova**:

1. valjan diff bez `diff --git` reda — odbio ga je **naš parser** (ADR-0048);
2. ponovna predaja iste zakrpe — izazvana time što je **naš prompt** tvrdio da mu
   rad stoji na grani (ADR-0050, ADR-0051);
3. zakrpa na grani `zadatak/TSK-…EXMSG` — ispravna, sa četiri zelene kapije, ali
   ju je **pretekla ručna zakrpa** jer recenzija nije završena na vreme.

Svaki od ta tri uzroka je popravljen svojim ADR-om. Nijedan nije popravio broj.

ADR-0048 je zapisao: *„mera koja tuđu grešku pripisuje agentu gora je od mere koje
nema, jer se po njoj odlučuje."* Tri dana kasnije, mera je i dalje radila tako.
Popravljali smo uzroke i ostavljali merilo — a upravo po merilu treba da se odlučuje
o poverenju, o izboru modela i o tome ko od 10.000 agenata dobija koji posao.

## Odluka

### 1. `TaskPatch.fault` — tri vrednosti

| vrednost | značenje |
|---|---|
| `AGENT` | agent je promašio: putanja van dozvoljenih, zaštićena zona, nečitljiv diff |
| `SISTEM` | **naš** kvar je odbio valjan rad |
| `COVEK` | ljudska odluka: rad pretekla ručna zakrpa, ili je otkazan |

Podrazumevano je `AGENT` — u redovnom slučaju odbijanje jeste njegovo, i teret
dokazivanja je na onome ko tvrdi suprotno.

### 2. Krivicu pripisuje isključivo čovek, uz obavezan razlog

`zakrpa.pripisi_krivicu(zakrpa, krivica, *, actor, razlog)`. Tri granice, iste kao
kod ponovnog otvaranja nalaza (ADR-0050):

- **samo čovek** (`actor` počinje sa `user:`). Ovo je presuda o tuđem radu, ne
  merenje. Mašina koja bi sama sebe oslobađala krivice ne bi merila ništa;
- **razlog je obavezan** i ide u zapis (`task.patch.fault_assigned`, WARNING). Bez
  njega bi `ucinak` imao broj koji niko ne može da potkrepi — tačno ono što
  ADR-0033 zabranjuje;
- **samo odbijena zakrpa.** Na prihvaćenoj krivica nema smisla.

**Status se ne dira.** Zakrpa je odbijena i ostaje odbijena; menja se ko za to
odgovara. Zapis se ne doteruje da bi brojevi izgledali bolje (ADR-0046).

### 3. `ucinak` razdvaja, ne oduzima

Nova kolona `NE NJEG` stoji pored `ODBIJ.`, a ne umesto nje. Broj odbijanja ostaje
tačan; uz njega stoji koliko ih ne pada na agenta, i svaki od tih ima razlog u
zapisu.

`zakrpa_prihvaceno` se od sada računa **bez** zakrpa oborenih tuđom krivicom — ni u
brojiocu ni u imeniocu. Zakrpa koju je odbio naš parser nije bila agentova prilika,
pa nije ni njegov promašaj.

Komanda: `manage.py krivica --zadatak TSK-… --spisak`, pa
`manage.py krivica --zakrpa <prefiks> --kome SISTEM --zasto "…"`.

## Šta je odbačeno

- **Automatsko prepoznavanje naših kvarova** iz teksta `reason` (npr. „nije vratio
  diff" → SISTEM). Uzrok se vidi tek kad se zna šta je lanac u tom trenutku radio;
  pravilo napisano po obrascu odbilo bi i stvarne agentove promašaje istog teksta.
- **Brisanje ili prepravljanje odbijenih zakrpa.** Zapis ostaje; dodaje mu se ko
  odgovara (ADR-0046, ADR-0049).
- **Nov `PatchStatus`.** Krivica nije stanje zakrpe u lancu provera; enum se ne širi
  za nešto što nije ishod.
- **Podrazumevano `None` umesto `AGENT`.** Tada bi svaka nova zakrpa ulazila kao
  „nepoznato" i `ucinak` ne bi mogao da izračuna ništa dok neko ručno ne prođe sve.
  Podrazumevano `AGENT` je i pošteno: odbijanje je njegovo dok se ne dokaže drugo.
- **Retroaktivno popunjavanje migracijom.** Ne znamo ko je kriv za zatečene redove;
  svaki se pripisuje ručno, sa razlogom. Tri poznata slučaja se upisuju odmah.

## Posledice

- `common/enums.py` → `PatchFault`; `TaskPatch.fault`, `TaskPatch.fault_reason`;
  `zakrpa.pripisi_krivicu`; `manage.py krivica`; `ucinak` → nova kolona i izmenjen
  `zakrpa_prihvaceno`.
- **Migracija `0010_krivica_odbijanja`** — dodaje polja, ne popunjava ih.
- 10 novih provera; ukupno 1005.

## Zapisano za ADR-0033

Ovo nije bila pretpostavka nego **odlaganje**. Obrazac je zapisan tri puta —
26.09. u ADR-0048, 27.09. u ADR-0049 i ADR-0050 — i svaki put je zaključak bio
„popravljen je uzrok". Nijednom nisam otišao do kraja i pitao šta se dešava sa
brojem koji je već upisan.

Pravilo koje iz toga sledi: **kad se popravi uzrok, proverava se i šta je taj uzrok
već upisao u meru.** Popravka koja ne dodirne zatečeni zapis ostavlja laž koja i
dalje radi.
