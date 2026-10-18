# ADR-0115 — Prilozi u niti (veza i tekstualni fajl)

- **Status:** prihvaćen (18.10.2026.) — increment 1
- **Povod:** Čovek je direktoru mogao da pošalje samo rečenicu. Za stvaran
  posao treba i materijal: veza ili fajl od kog agent radi.
- **Prethodi:** ADR-0103/0104 (fajl u skladištu), ADR-0105 (ulazna vrata),
  ADR-0110 (delovi poruke)
- **Menja:** `apps/orchestration/models.py` (model `Prilog`), migracija `0016`,
  `apps/orchestration/razgovor.py`, `console/views.py`,
  `console/templates/console/razgovor.html`, `console/static/console/console.css`,
  `tests/test_razgovor.py`, `tests/test_models.py`

## Odluka

**1. Prilog stoji uz čovekovu poruku.** Nov model `Prilog` (`vrsta` veza|fajl,
`naziv`, `url` za vezu, `asset`→`MediaAsset` za fajl), vezan na `Poruka`.

**2. Telo vs materijal (nadovezuje se na ADR-0110).** `posalji()` sada prima i
`materijal` — ono od čega direktor radi — odvojeno od `telo` koje čovek vidi.
Uz prilog, sadržaj tekstualnog fajla se utka u `materijal` (do 2500 znakova),
a `telo` u niti ostaje čisto. Tako agent zna šta mu je dato, a nit ne postaje
smetlište sadržaja fajla.

**3. Fajl se čuva, veza se samo zapisuje.** Tekstualni fajl ide u skladište
kao `MediaAsset` (kind DOCUMENT, origin `user_owned`), filovan pod direktorom
koji ga je primio, i preuzima se iz niti preko `/console/assets/<id>`. Veza se
**ne poseduje** — nema odlaznih zahteva (prekidač spoljnih radnji je isključen);
agent je vidi kao referencu, ne ide po nju.

**4. Increment 1 prima samo tekst i vezu.** `.txt`, `.md`, `.csv` (≤ 1 MB) i
`http(s)` veza. Slike i PDF se **ne primaju** — agent ih još ne čita (nema
vida ni izvlačenja teksta iz PDF-a). To je svesna granica, ne propust; kad se
to doda, biće svoj ADR.

## Bezbednost

- Tip fajla se proverava (MIME + ekstenzija), veličina se ograničava (1 MB).
- Veza mora da počne sa `http(s)://`; prikazuje se sa `rel="noopener
  noreferrer nofollow"`, ne otvara se sa servera.
- Prekidač spoljnih radnji ostaje isključen; ništa se ne dohvata.

## Šta ovo NE radi (sledeći inkrementi)

- Nema slike/PDF-a i nema vida.
- Nema izvlačenja teksta iz .docx/.odt priloga (samo čist tekst).
- Prilog se ne prosleđuje kroz lanac kao zaseban objekat — njegov sadržaj je
  u materijalu; izvršilac ga vidi kroz zadatak, ne kao fajl u svom koraku.
