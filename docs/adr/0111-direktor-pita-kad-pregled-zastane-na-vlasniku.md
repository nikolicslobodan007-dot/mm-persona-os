# ADR-0111 — Direktor pita kad pregled zastane na vlasniku

- **Status:** prihvaćen (18.10.2026.)
- **Povod:** Prvi pregled po ADR-0108 je radio, ali kad je Mila vratila nacrt
  rečima „*trebalo je od vlasnika tražiti pojašnjenje*", direktor je čoveku
  javio **„Nije urađeno"** — umesto da ga **pita**. Vlasnik je izabrao:
  direktor pita samo kad šef traži baš njegov ulaz; zanatsku grešku javlja kao
  neuspeh.
- **Prethodi:** ADR-0106 (direktor procenjuje), ADR-0108 (šef pregleda),
  ADR-0110 (delovi poruke)
- **Menja:** `apps/content/pregled.py`, `apps/content/steps.py`,
  `apps/orchestration/razgovor.py`, `tests/test_razgovor.py`

## Odluka

**1. Šef pri vraćanju odlučuje još jedno: da li posao zastaje na vlasniku.**
Pregled (`content.review`) uz `prihvatam`/`primedba` daje i
`trazi_vlasnika` (bool) i `pitanje` (vlasniku). Zanatsku grešku koju izvršilac
može sam da ispravi (predugačko, loš naslov) šef NE gura vlasniku.

**2. Dve grane vraćanja:**
- `trazi_vlasnika` + pitanje → direktor vlasniku postavlja to pitanje u niti
  (`stanje: pitanje`), ne „nije urađeno".
- sve ostalo → kao dosad: „Nije urađeno… posao je stao: <primedba>".

**3. Signal putuje kroz razlog pada.** Vraćen nacrt obara korak; kad traži
vlasnika, razlog nosi prefiks `[[PITANJE-VLASNIKU]]`. On se penje nagore
(`_resume_parent`) do direktorovog plana, gde ga `razgovor.posalji` prepoznaje
pre nego što sastavi poruku „stalo". Prefiks je **štampajući, bez null-bajta**
— razlog ide u `output_json` (JSONB), a PostgreSQL ne prima `\u0000`.

**4. „Treba vlasnik" bez pitanja se ne prihvata.** `trazi_vlasnika: true` sa
praznim `pitanje` tretira se kao vraćanje bez razloga (ADR-0108, tačka 6):
pada na obično vraćanje, ne na pitanje bez sadržaja.

**5. Pitanje ne nosi plan.** Kao kod direktorove procene (ADR-0106), poruka sa
pitanjem je bez plana: posao je zastao, a vlasnikov odgovor kreće kao nov
zahtev.

## Cena, iskreno

Kad posao zastane na vlasniku, nacrt koji je izvršilac napisao se **gubi** —
vlasnikov odgovor pokreće nov lanac od početka. To je svesno, dok nema drugog
kruga (ADR-0108): bolje čist nov pokušaj sa pojašnjenjem nego krpljenje
polovičnog nacrta. Kad uvedemo drugi krug, ovo se meri ponovo.

## Šta ovo NE radi

- **Ne uvodi drugi krug.** I dalje nema vraćanja izvršiocu na ispravku.
- **Ne odlučuje umesto šefa** da li nešto traži vlasnika — to je šefov sud,
  kao i sam pregled; bez modela (lokalni šablon) nema ni pregleda ni pitanja.
