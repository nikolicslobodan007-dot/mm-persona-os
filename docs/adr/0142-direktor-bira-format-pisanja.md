# ADR-0142 — Direktor bira format pisanja (dug članak dobija svoj budžet)

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Živa proba (Telegram): „napiši dubinski članak…". Recenzent (šef)
  je ispravno ODBIO nacrt jer je „prekratak i nedovršen za dubinski članak" —
  dokaz da recenzentska kapija (ADR-0108) radi s pravim modelom. Ali uzrok je
  bio rutiranje: direktor je svaki zahtev za pisanje slao kao `objava` (budžet
  ~800 tokena), pa je i članak ispao dužine objave.
- **Prethodi:** ADR-0133 (vrste zadataka/ZADACI sa `izlaz_tokena` i strukturom),
  ADR-0108 (recenzija), ADR-0136/0139 (rutiranje po vrsti).
- **Menja:** `apps/orchestration/razgovor.py` (direktor bira format, `_koraci`
  prosleđuje ga u `content.draft`), `apps/content/steps.py` (`_draft` diže
  `Zadatak` po formatu), testovi.

## Odluka
`vrsta` sada obuhvata i **formate pisanja** iz ZADACI (javni, ne-interni):
`objava`, `dubinski-clanak`, `nit`, `newsletter`, `video-scenario` — uz
postojeće task-tipove `prepis-videa`, `sazetak-weba`. Direktor (ODLUKA_SYSTEM)
bira format po tome šta vlasnik traži; `_koraci` kači izabrani format u ulaz
`content.draft` koraka (osim `objava`, koja ostaje podrazumevani put bez
promene). Handler `content.draft` tada digne `Zadatak` iz ZADACI i preda ga
`service.draft`, koji već koristi njegov `izlaz_tokena` (npr. članak 1600),
`uputstvo` (struktura: teza, 3–4 odeljka, izvori, zaključak) i `format`
(ARTICLE/THREAD/…). Infrastruktura je već postojala (ADR-0133) — povezano je
samo rutiranje.

Interni artefakti (battlecard, outreach, plan-naloga) se NE rutiraju kroz
razgovor — oni idu kroz `agent_zadatak` (showcase), pa su van dozvoljenih
`vrsta`.

## Posledice
- „Napiši dubinski članak / analizu / nit / newsletter / video-scenario" sada
  dobija pravi budžet i strukturu, pa recenzent nema šta da odbije zbog dužine.
- `objava` nepromenjena (ne kači Zadatak) — bez rizika po postojeće ponašanje.

## Granice (za kasnije)
- Vrlo dug članak i dalje je jedan prolaz modela (do ~1600 tokena). Pisanje po
  sekcijama (više poziva, pa spajanje) je zaseban sloj ako zatreba.
