# ADR-0108 — Šef pregleda pre nego što vrati

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Posle ADR-0105/0106 lanac radi: direktor procenjuje, šef dobija
  posao, izvršilac piše, nacrt se vraća u nit. Ali šef je u tom lancu bio
  **poštar**: korak kojim je „preuzimao gotov posao" je `plan.note`, a on po
  projektu ne radi ništa. Srednji nivo je postojao kao ime, ne kao posao.
- **Prethodi:** ADR-0017 (delegiranje ne daje dozvolu), ADR-0022 (posao se
  vraća nalogodavcu), ADR-0024 (koraci sadržaja), ADR-0105, ADR-0106, ADR-0107
- **Menja:** `apps/content/pregled.py` (novo), `apps/content/steps.py`,
  `apps/orchestration/plans.py`, `apps/orchestration/razgovor.py`,
  `tests/test_razgovor.py`
- **Canon:** §13.2 (svrha poziva modela), §17 (oznaka AI)

## Odluka

**1. Šefov korak je `content.review`, a ne beleška.** U šefovom planu, posle
koraka kojim je zadao izvršiocu, stoji pregled. Izvršava ga šef, u svom planu,
svojim poverenjem. Delegiranje mu ne daje nikakvo novo pravo (ADR-0017).

**2. Nacrt se traži kroz lanac.** Nacrt je nastao u planu izvršioca, ne u
šefovom. Zato je iz `razgovor._nacrt_iz_lanca` izvučena opšta funkcija
`plans.output_in_chain(plan, handler)`: izlaz prvog **završenog** koraka tog
obrađivača u planu ili ispod njega. U lanac se silazi i kad je korak pao — jer
nacrt koji nije prošao pregled i dalje postoji i čovek treba da ga vidi.

**3. Čita se ceo nacrt.** Izlaz koraka `content.draft` nosi prvih 400 znakova;
pregled uzima `ContentItem.body`. Pregled polovine teksta nije pregled.

**4. Vraćen nacrt zaustavlja posao, sa razlogom.** Korak pada sa tekstom
„*<šef> vraća nacrt: <primedba>*“, posao se vraća direktoru kao neurađen
(ADR-0022), a direktor čoveku javlja razlog **i nacrt koji nije prošao**. Bolje
spor koji se vidi nego tiho prihvaćen tekst.

**5. Pregled je dodatak, ne uslov.** Bez modela, ili kad model vrati nešto što
nije sud, nacrt prolazi kao pre i to se zapisuje
(`content.pregled.bez_modela`, `content.pregled.bez_suda`). Agent bez ključa ne
sme da ostane bez posla, samo bez pregleda.

**6. Vraćanje bez razloga se ne prihvata.** `{"prihvatam": false, "primedba":
""}` nije pregled nego prepreka: sud se odbacuje, nacrt prolazi, zapisuje se
`content.pregled.bez_razloga`.

**7. Svrha poziva je `EVALUATE`**, ne `CONTENT_DRAFT`: drugi posao, druga ruta,
svoj budžet (Canon §13.2). **Posledica koja se mora znati:** ako za `evaluate`
ne postoji uključena ruta, `routes()` vraća lokalni šablon, šablon ne ume JSON
i pregled se **ne dešava** — tiho, po pravilu 5. Zato direktor u odgovoru
tvrdi da je nacrt pregledan **samo ako je suda stvarno bilo** (`presudio`).

**8. Potpis izvršioca ne ide u direktorovu poruku.** Oznaka AI persone (§17)
ostaje na nacrtu u bazi i na svemu što izlazi napolje; iz teksta koji direktor
prepisuje u nit se skida, jer tu poruku potpisuje direktor. Dva potpisa u
jednoj poruci čoveku govore da mu piše izvršilac, a ne direktor.

## Šta ovo NE radi

- **Nema drugog kruga.** Vraćen nacrt se ne vraća izvršiocu na ispravku —
  posao staje i čovek odlučuje. Krug ispravke je svoja odluka, sa svojim
  ograničenjem broja prolaza.
- **Šef ne prepisuje nacrt.** Ili prihvata, ili vraća sa primedbom. Pisanje
  ostaje izvršiočev posao.
- **Šef koji radi sam se ne pregleda.** Kad sektor nema izvršioca, šef piše
  nacrt lično; pregled svog teksta nije pregled, pa koraka nema.
