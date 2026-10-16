# ADR-0106 — Direktor procenjuje pre nego što zada

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Posle ADR-0105 čovek piše Ivani, ali ona samo prosleđuje. Rečenica
  „napiši nešto za sajt" stiže izvršiocu doslovno, pa i naslov nacrta postaje
  doslovno ono što je čovek otkucao.
- **Prethodi:** ADR-0009 (gateway), ADR-0017, ADR-0105
- **Menja:** `apps/orchestration/razgovor.py`, `tests/test_razgovor.py`
- **Canon:** §13.2 (svrha poziva modela), §3.11

## Odluka

**1. Direktor prvo procenjuje, pa zadaje.** Pre delegiranja, poruka ide modelu
sa svrhom `PLANNING` (postoji, ne dodaje se enum) i direktor vraća tri stvari:
sektor, **nalog svojim rečima**, ili **jedno pitanje**.

**2. Pitanje zaustavlja posao, i to je dobro.** Ako direktor pita, ništa se ne
delegira i plan se ne pravi — u niti stoji samo pitanje. Posao koji kreće bez
dovoljno podataka troši i vreme i novac, a vrati nešto što se baca.

**3. Nalog zamenjuje sirovu rečenicu.** Ono što ide izvršiocu je direktorov
nalog, ne čovekova poruka. Odgovor to i kaže (*„Zadatak koji sam prosledila:
…"*), da čovek vidi kako je shvaćen. Usput se rešava i to što je naslov nacrta
do sada bio ceo prompt.

**4. Procena je dodatak, ne uslov.** Ako modela nema, ako padne, ili ako vrati
nešto što nije JSON — procena je prazna i sve radi kao u ADR-0105: tabela reči
i doslovna tema. Lokalni šablon ne ume JSON i **to je očekivano**, ne greška.
Agent bez ključa ostaje bez procene, ne bez posla. Za to postoje tri testa.

**5. Izmišljen sektor se ne prihvata.** Vrednost van spiska pada na tabelu
reči. Model predlaže, kod proverava.

**6. Poziv ide kroz `gateway.generate`** — ista vrata kao za sve ostalo, pa
ruta, dozvola, cena i zapis stoje na jednom mestu (ADR-0009). Direktor ne
dobija svoj kanal ka modelu.

## Šta ovo NE radi

- **Direktor i dalje ne ocenjuje rezultat.** Prosleđuje ga kakav je. Pregled
  gotovog posla je posao šefa sektora i sledeća odluka.
- **Pitanje nema nastavak.** Ako direktor pita, čovek odgovori novom porukom i
  to je nov krug — ne pamti se da je prethodna poruka čekala odgovor.
- **Jedno pitanje, ne razgovor.** Namerno: direktor koji pita tri puta pre nego
  što išta uradi gori je od onog koji ne pita.
