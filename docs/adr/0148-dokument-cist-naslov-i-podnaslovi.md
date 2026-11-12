# ADR-0148 — Dokument: čist naslov i stilizovani podnaslovi

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Prvi PDF (ADR-0147) radi, ali izgled je osnovan: naslov je bio
  **sirov direktorov nalog** („Napisati dubinski članak … o … direktor, šef",
  isečen usred reči), a **podnaslovi** se utapali u tekst (telo deljeno samo po
  praznom redu, sve kao pasusi). Izgledalo je kao zid teksta.
- **Prethodi:** ADR-0103 (nacrt → fajl), ADR-0147 (PDF dostava).
- **Menja:** `apps/content/dokument.py` (`_cist_naslov`, `_blokovi`, `_projekat`).

## Odluka
Dokument se gradi čitljivije, bez diranja sadržajnog lanca i bez poziva modelu:

- **`_cist_naslov(sirov)`** — skida instrukcioni uvod („Napiši … o ") i uzima
  jezgro teme (do prvog zareza/zagrade/„oslanjajući"), pa veliko prvo slovo i
  razumna dužina. Kratak, čitljiv naslov umesto naloga.
- **`_blokovi(telo)`** — telo → (podnaslov | pasus). Kratka samostalna linija
  bez završne interpunkcije, sa telom posle, je **podnaslov** (heading 2); `##`
  markdown se takođe prepoznaje. Disclosure linija (počinje crtom) ostaje pasus.
- **`_projekat`** — naslov kao heading 1, podnaslovi kao heading 2, ostalo
  pasusi. LibreOffice ih sada renderuje sa pravom hijerarhijom.

## Posledice
- PDF (i docx) imaju čist naslov i vidljive podnaslove — korak ka „ChatGPT
  izgledu". Čiste funkcije (`_cist_naslov`, `_blokovi`) su jedinično testirane.

## Granice (za kasnije)
- Naslov iz dativa (npr. „Prednostima i rizicima…") nije uvek gramatički naslov;
  nominativ bi tražio obradu padeža (ili da naslov daje pisac/direktor).
- Zaglavlje/brend (logo, boje) i tabele su sledeći sloj stilizacije.
