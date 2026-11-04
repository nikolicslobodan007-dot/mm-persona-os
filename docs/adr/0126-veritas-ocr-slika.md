# ADR-0126 — Veritas čita tekst sa slike (OCR, Tesseract); URL slike → nalaz

- **Status:** prihvaćen (04.11.2026.)
- **Povod:** Mnogo „tvrdnji" stiže kao slika sa ugoranim tekstom (memeovi,
  screenshotovi, npr. crveni „Aca Srbin" post) — bez zvuka, pa `veritas_klip`
  (ASR) ne pomaže. Slice 3.1: URL slike → OCR → nalaz (+ opc. verdikt).
- **Prethodi:** ADR-0125 (Slice 3 ASR), ADR-0118 (vision prilozi), ADR-0009 (offline)
- **Canon:** §2.2 (MediaAsset), §8 (AssetKind)

## Odluka

**1. OCR motor je Tesseract (lokalno).** Sistemski paketi `tesseract-ocr` +
`tesseract-ocr-srp` u Dockerfile-u; tanak Python omotač `pytesseract` + `Pillow`.
Besplatno, offline (ADR-0009), bez ključa, nula LLM troška za ekstrakciju. Jezik
`srp_latn+srp+eng` (latinica + ćirilica + engleski), uz rezervu na podrazumevani
jezik ako neki model nije prisutan.

Zašto ne vision LLM (ADR-0118): za jasne memeove Tesseract je dovoljan i besplatan;
vision ostaje kao moguća nadogradnja za loše/fotografisane slike. OCR je čist
EXTRACT korak — razumevanje (ironija, implikacije) radi `nalaz`, kao i do sada.

**2. Tok (Slice 3.1).** `veritas_slika --url <URL>` → `slika.procitaj`:
skine sliku (UA zbog Cloudflare-a — ADR-0125 lekcija; SSRF brana preko Libri
`uvoz_web.proveri_bezbedan`) → Tesseract izvuče tekst → MediaAsset (kind=PHOTO,
ključ `veritas/slika/<sha>.<ext>`, isto skladište ADR-0018) → `izlaz` izvuče
nalaze i opc. donese verdikt (`--proveri`).

**3. Zajednički prikaz `izlaz.py`.** „Tekst → nalazi → verdikt" je izdvojeno iz
`veritas_klip` u `veritas.izlaz.prikazi_nalaze(cmd, tekst, o)`; dele ga `veritas_klip`
(zvuk) i `veritas_slika` (OCR), bez duplikata.

## Posledice
- Veritas sada pokriva i tekst-na-slici, ne samo zvuk. Sarkazam/ironija se vide
  kad doslovni i implicirani sloj idu u suprotnim smerovima (baš „Aca Srbin").
- `pytesseract`/`pillow` dodati u zavisnosti; Tesseract paketi u sliku (duži prvi build).
- Anonimni/satirični izvor (npr. „Aca Srbin") ostaje nizak po pouzdanosti — verdikt to odražava.

## Rizik
- Loš kvalitet/rukopis/fotka → slab OCR; tada je vision LLM (ADR-0118) nadogradnja.
- `tesseract-ocr-srp` latinicu (`srp_latn`) pokriva zavisno od distribucije; ako
  latinica slabo ide, dodaje se `tesseract-ocr-script-latn`.
