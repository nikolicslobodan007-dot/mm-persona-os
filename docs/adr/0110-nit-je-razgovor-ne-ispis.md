# ADR-0110 — Nit je razgovor, ne ispis

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Lanac je proradio, ali vlasnik je o ekranu kroz koji razgovara sa
  svojom firmom rekao: *„interfejs je i dalje blagi užas! Da sam ja klijent, ne
  bih dao ovima ni da mi čuvaju ovce."* I bio je u pravu: nalog, ishod, pregled
  i nacrt stajali su kao jedan sivi blok teksta, a pored nacrta nije bilo
  nijednog dugmeta.
- **Prethodi:** ADR-0104 (dokument iz konzole), ADR-0105, ADR-0108, ADR-0109
- **Menja:** `apps/orchestration/models.py`, migracija `0015`,
  `apps/orchestration/razgovor.py`, `console/views.py`,
  `console/templates/console/razgovor.html`,
  `console/static/console/console.css`, `tests/test_razgovor.py`

## Odluka

**1. Poruka nosi i razložen oblik.** Novo polje `Poruka.delovi` (JSON) drži
`stanje`, `nalog`, `sef`, `izvrsilac`, `pregled`, `razlog`, `nacrt`, `item`,
`plan`. Konzola prikazuje delove; **ne razbija rečenice**.

**2. `telo` ostaje potpuno.** Zapis u bazi i dalje sadrži sve u rečenicama —
poruka mora da se razume i bez konzole (izvoz, revizija, stariji prikaz).
Oboje nastaje iz **jednog** izvora (`_ishod` → `_tekst`), pa ne mogu da se
raziđu; za to postoji test.

**3. Stara poruka bez delova se i dalje prikazuje** — prazan `delovi` znači
„pokaži `telo`". Migracija ne prepisuje istoriju.

**4. Nacrt ima dugme.** „Napravi dokument" stoji uz nacrt u niti i vraća se u
nit (ADR-0104 je dokument vezao za spisak sadržaja; sada se do njega dolazi i
odatle gde je nacrt nastao). Polje `nazad` prima **samo** putanju koja počinje
sa `/console/` i nema `//` — inače je to otvoreno preusmerenje.

**5. Čovek i agent se razlikuju na prvi pogled**, pregled je obojen po ishodu
(prihvaćeno zeleno, vraćeno crveno), nacrt je u svom okviru sa zaglavljem, a
nit je široka najviše 84 znaka, jer se tekst duže od toga ne čita nego skenira.

## Šta ovo NE radi

- **Nema priloga u niti** (fajl, slika, veza) — to je svoja odluka.
- **Nema osvežavanja uživo**: posao se i dalje izvršava u istom zahtevu i
  čovek čeka. Kad lanac poraste, ide u red poslova i tek tada ima smisla
  pokazivati korake dok teku.
- **Ne menja šta agent radi** — samo šta čovek vidi.
