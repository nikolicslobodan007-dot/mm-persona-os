# ADR-0019 — Konzola v2: pregledniji raspored

- **Status:** prihvaćeno
- **Datum:** 24.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §16.4 · ADR-0010 (konzola), ADR-0017, ADR-0018
- **Kod:** `console/templates/console/*`, `console/static/console/console.css`,
  `console/static/console/console.js`, `tests/test_console.py`

## Kontekst

Konzola je nastala uz F8 kao najmanji mogući alat za operatera i od tada je
dobila šest novih kartica (pošta, pouke, organizacija, dosije, lik…). Strana
agenta je postala jedan dugačak niz kartica kroz koji se mnogo skroluje, tekst
je bio sitan, a ništa nije govorilo **šta traži čoveka odmah**. Slobodan je
naveo sve četiri smetnje (24.09.): sitno i gusto, previše na jednoj strani, ne
vidi se šta je važno, izgled siromašan.

## Odluke

1. **Bočna navigacija umesto trake na vrhu**, podeljena u tri grupe:
   *Rad* (Pregled, Odobrenja, Sadržaj), *Korporacija* (Agenti, Organizacija),
   *Nadzor* (Troškovi, Incidenti). Svaka stavka ima ikonu; broj odobrenja na
   čekanju stoji kao crveni brojač uz stavku. Na užem ekranu se traka vraća na
   vrh i lomi u redove.
2. **Strana agenta dobija tabove:** Stanje · Lik i dosije · Sadržaj · Pošta ·
   Pravila i poverenje · Akcije. Bez JavaScript-a su svi odeljci vidljivi (kao
   i do sada), a skripta samo skriva sve osim izabranog — dakle strana radi i
   kad skripta ne prođe. Izbor se pamti u adresi (`#lik`), pa se link može
   poslati i osvežavanje ne vraća na prvi tab.
3. **Traka „Traži tebe" na vrhu Pregleda.** Nabraja samo ono što stvarno čeka:
   aktivan kill-switch, akcije na odobrenju, otvorene incidente i neuspele
   objave — svaku sa linkom na mesto gde se rešava. Kad nema ničega, na istom
   mestu piše „Ništa ne čeka", da odsustvo poruke bude odgovor, a ne praznina.
4. **Jedinstven naslov strane** (`page-head`): naslov, jedna rečenica šta je
   ta strana, i statusne oznake desno. Isti oblik na svih osam strana.
5. **Tipografija i vazduh:** osnovni tekst 16 px (bio 15), tabele 15 px,
   naslovi 27/18 px, veći razmaci u karticama, mekša senka i veći radijus.
   Tabele parova ključ-vrednost dobijaju `table.plain` (bez linija, uži prvi
   stubac), pa se dosije i „šta je akcija" čitaju kao spisak, ne kao rešetka.

## Šta nije dirano

Sav sadržaj strana, imena polja, tokovi odobravanja i dozvole ostaju isti —
ovo je promena rasporeda i stila, ne ponašanja. CSP i dalje zabranjuje inline
stil i skriptu, pa je sve u `console.css` i `console.js`; test to i dalje
proverava.

## Posledice

- Milina strana više nema beskrajno skrolovanje: svaki odeljak je jedan klik.
- Operater na Pregledu odmah vidi ima li šta da uradi.
- 463 testa (dodato 4: bočna navigacija i grupe, traka pažnje u oba stanja,
  tabovi i odeljci na strani agenta).
