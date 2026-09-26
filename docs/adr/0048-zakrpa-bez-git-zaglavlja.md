# ADR-0048 — Zakrpa bez `diff --git` zaglavlja je i dalje zakrpa

- **Status:** prihvaćen (26.09.2026.)
- **Prethodi:** ADR-0044 (pisac), ADR-0038 (zakrpa), ADR-0042 (merenje),
  ADR-0033 (pravilo nula)
- **Menja:** ADR-0044, stavku „Nagađanje diffa iz proze" u *Šta je odbačeno*

## Šta se desilo

Drugi pokušaj po recenziji nije stigao do kapija. Red je ćutao sedam minuta, a
kad smo pogledali:

```
10:41  APPLIED   kapija: 4  sha: d0d125fd484f  znakova: 2160
13:56  REJECTED  kapija: 0  sha: -             znakova: 3256
razlog: model nije vratio diff
```

Model je vratio **ispravan unified diff** — sa `--- a/apps/content/lessons.py`,
`+++ b/…` i urednim hunk-ovima. Jedino nije napisao red `diff --git`.

Taj red nije deo unified diff formata; to je `git`-ov dodatak. `git apply` prima
zakrpu bez njega, a i naš `zakrpa.paths_in` je čita preko `---` i `+++` redova
— provera putanja bi radila normalno. Samo je `pisac.izvuci_diff` tražio baš
`^diff --git ` kao jedini znak da je nešto zakrpa, i valjan rad bacio kao prozu.

## Zašto je ovo gore od izgubljenog poziva

Neuspeh je upisan kao **agentov**. U `ucinak`-u je P-00027 dobio jednu prihvaćenu
i jednu odbijenu zakrpu — pedeset posto — zbog greške u našem parseru.

ADR-0042 je celu meru gradio na tome da brojevi budu pošteni. Mera koja tuđu
grešku pripisuje agentu gora je od mere koje nema, jer se po njoj odlučuje.

## Odluka

### 1. Zakrpa počinje na dva načina

`izvuci_diff` prihvata `^diff --git ` **ili** par `^--- <put>` pa odmah
`^+++ <put>`, i seče od onoga što je ranije.

### 2. Traži se par, ne jedan red

Sam `---` je markdown crta i pojavljuje se u prozi. Par `---`/`+++` u dva
uzastopna reda, sa nepraznim putanjama, ne pojavljuje se slučajno. Odluka iz
ADR-0044 da se **diff ne nagađa iz proze** ostaje; menja se samo to koji oblik se
priznaje kao diff, a ne da li se nagađa.

### 3. Odbijena zakrpa iz ove greške ostaje u bazi

Ne briše se i ne prepravlja joj se status. Ona je tačan zapis onoga što se
desilo; netačno bi bilo tumačiti je kao agentov promašaj. Zato ovaj ADR postoji i
zato se u `stanje-rada` vodi kao **naša** greška.

Ista zakrpa se predaje ponovo, iz sačuvanog teksta, u ime P-00027 — model ju je
napisao i ne plaća se drugi put.

## Šta je odbačeno

- **Traženje `diff --git` uz uputstvo modelu da ga obavezno piše.** Uputstvo koje
  mora da se ispoštuje da bi ispravan ulaz prošao nije provera nego zamka.
- **Prihvatanje svega što ima `---` u sebi.** Tada bi svaki markdown naslov bio
  zakrpa.
- **Ispravljanje statusa odbijene zakrpe u bazi.** Zapis se ne doteruje da bi
  brojevi izgledali bolje (ADR-0046).
- **Ćutke veća tolerancija u `zakrpa.check`.** Provera putanja se ne dira; problem
  je bio isključivo u tome šta je uopšte stiglo do nje.

## Posledice

- `pisac._pocetak`, izmenjen `izvuci_diff`; 8 novih provera u `tests/test_pisac.py`.
- Nema migracije. `zakrpa.py` nije diran.

## Zapisano za ADR-0033

Dve moje pretpostavke u jednom danu, obe iste vrste:

1. **Da je `diff --git` obavezan.** Nije; nikad nisam proverio, a `zakrpa.py` koji
   sam čitao pokazivao je suprotno — `_MINUS` i `_PLUS` rade i bez njega.
2. **Da je zakrpa prihvaćena, jer sam video njen tekst.** Ispis diff-a pokazuje
   najnoviju zakrpu bez obzira na status; odbijene se čuvaju (ADR-0038 §3). Ispis
   komande `pisac`, koji je crvenim slovima rekao `REJECTED`, otišao je uz ekran i
   nisam ga tražio. Na osnovu toga sam **zatvorio dva nalaza kao `FIXED`** nad
   zakrpom koja nije primenjena.

Druga je opasnija: prva je odbila valjan rad, druga je upisala neistinu u zapis
recenzije. Pravilo koje iz toga sledi: **status se čita iz polja koje ga nosi, ne
iz toga što sadržaj izgleda gotovo.**
