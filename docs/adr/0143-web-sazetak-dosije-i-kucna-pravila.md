# ADR-0143 — web.sazetak dobija dosije firme; kućna pravila pisanja

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Cilj vlasnika: „Ivana da proceni da li je ono što sam joj poslao
  korisno za WK — ako jeste, zašto i kako da implementiramo; ako nije, zašto."
  Handler `web.sazetak` je odgovarao na nalog (ADR-0140), ali BEZ dosijea firme
  — pa je „korisno za WK" procenjivao naslepo, bez konteksta šta je WK. Uz to,
  recenzent je na članku dva puta hvatao potpis ličnim imenom i opšta znanja
  (EU AI Act) predstavljena kao praksa firme.
- **Prethodi:** ADR-0139/0140 (web.sazetak + ugao), ADR-0107 (dosije firme),
  ADR-0108 (recenzija), ADR-0142 (format pisanja).
- **Menja:** `apps/memory/sakupljanje/steps.py` (dosije u web.sazetak prompt),
  `apps/content/service.py` (KUCNA_PRAVILA u content prompt), testovi.

## Odluka
1. **web.sazetak + dosije firme.** Handler sada prepinja `_dosije_firme()`
   (ADR-0107) na prompt, pa Ivana procenu „korisno za WK" radi sa kontekstom
   šta je WK, šta radi i za koga. Nalog (ugao) i dalje nosi pitanje
   („da li je korisno, zašto, kako implementirati"). Činjenice o izvoru ostaju
   iz teksta; činjenice o firmi iz dosijea.
2. **Kućna pravila pisanja (KUCNA_PRAVILA).** U content.draft prompt dodat
   kratak skup pravila: ne potpisuj tekst ličnim imenom (oznaka AI persone radi
   atribuciju); opšta znanja (regulativa, trendovi, tuđi primeri) pripiši kao
   opšta, ne kao praksu ove firme; o firmi tvrdi samo ono iz dosijea. Direktno
   gasi dve ponovljene primedbe recenzenta.

## Posledice
- Tvoj cilj (usefulness-analiza za WK) sada je uzemljen: Ivana zna prema čemu
  meri korist. Daš link → pitaš „da li je korisno za WK i kako" → dobiješ
  procenu vezanu za WK, ne opšti opis.
- Content pisanje ima manje šanse da padne na recenziji zbog potpisa i
  pripisivanja opštih znanja firmi.

## Granice (za kasnije)
- Ostaje **petlja ispravke** (revise loop): kad recenzent ipak odbije sa
  konkretnom kritikom, posao i dalje staje umesto da se vrati piscu na jednu
  ispravku. To je sledeći veliki lever (vidi nalaz-11-11-plafon-kvaliteta).
