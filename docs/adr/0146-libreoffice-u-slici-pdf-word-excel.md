# ADR-0146 — LibreOffice headless u slici: PDF, Word i Excel izvoz

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Vlasnik traži formatiran izlaz (PDF, kao u MercatoMaster-u), po
  mogućstvu i Word i Excel odjednom. `dokument.py` (ADR-0103) već ima presete za
  `docx`, `pdf` (i `xlsx` preko Calc-a), ali su radili samo `odt/html/txt` jer
  LibreOffice nije bio u slici — `docx/pdf` su padali jasnom greškom.
- **Prethodi:** ADR-0103 (nacrt → fajl preko cli-anything-libreoffice).
- **Menja:** `Dockerfile` (dodat `libreoffice-writer` + `libreoffice-calc`).

## Odluka
LibreOffice headless je jedan motor koji iz postojećeg koda daje **PDF i Word**
(Writer) i **Excel** (Calc) — nema nove biblioteke, samo paket u slici.
Instalira se sa `--no-install-recommends` da slika ostane manja:
- `libreoffice-writer` → odt/docx/pdf (proza: članci, analize);
- `libreoffice-calc` → xlsx (tabelarni podaci, kad zatreba).

Excel iz proze nema smisla — xlsx je za tabelarni sadržaj (zaseban tip, kasnije).
Iz proze prirodno izlaze PDF i Word; motor je sad tu za oba.

## Posledice
- PDF/docx izvoz radi u produkciji; odt/html/txt kao i pre.
- Slika je veća (par stotina MB) i build je sporiji — prihvaćen trade-off.
- CI nije dirnut: pokreće `pytest` na ubuntu-u (ne gradi sliku), a test za
  pdf/docx MOKUJE odsustvo LibreOffice-a (meri poruku, ne stvarno prisustvo).

## Granica (sledeći slajs)
- Dostava: Ivana pravi PDF i šalje ga na Telegram (`sendDocument` + lanac).
  Ovaj PR samo pali motor; dostava je zaseban korak.
