# ADR-0139 — Rutiranje zadatka po vrsti: „pregledaj link i sažmi" ide na web.sazetak

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Živa proba (Telegram): „pregledaj ovaj GitHub repo (kong/insomnia)
  i reci mi šta je to" → direktor je delegirao, ali izvršilac je opet zvao
  `content.draft`, pa je rezultat bila šuplja objava „o temi", a ne sažetak
  stvarnog sadržaja stranice. Isti problem koji je ADR-0136 rešio za video.
- **Prethodi:** ADR-0136 (rutiranje prepis-videa), ADR-0105/0106 (razgovor,
  procena), ADR-0135 (istorija niti). Oslanja se na `ulaz.procitaj("web", url)`
  (sakupljanje), koji za GitHub čita README.
- **Menja:** `apps/orchestration/razgovor.py` (`razmisli`/JSON šema vraća
  `vrsta="sazetak-weba"`, `_koraci` rutira, `_ishod` vadi sažetak preko
  `_ishod_sazetak`), `apps/orchestration/plans.py` (HANDLER_MODULES), nova
  `apps/memory/sakupljanje/steps.py` (handler `web.sazetak`), testovi.

## Odluka
**Treća vrsta zadatka uz `objava` i `prepis-videa`.** Kad vlasnik da link
stranice ili repozitorijuma i traži da ga pregledaš / sažmeš / pita „šta je
ovo", `razmisli` vraća `vrsta="sazetak-weba"` + `url`. `_koraci` tada gradi
lanac sa handlerom **`web.sazetak`** umesto `content.draft`.

Handler (`apps/memory/sakupljanje/steps.py`):
1. `ulaz.procitaj("web", url)` — učita tekst stranice (za GitHub: README).
2. `gateway.generate(CONTENT_DRAFT, …)` — kratak, tačan sažetak **samo iz
   teksta** (ulaz skraćen na 12.000 znakova), bez izmišljanja.
3. Vrati `{sažetak, naslov, izvor}`; `_ishod_sazetak` ga pošalje čoveku kao
   rezultat (sažetak kao nacrt, uz izvor).

Za razliku od video prepisa (ADR-0136), ovo **nije** blokirano — web fetch za
dovod radi sa servera i nije spoljna akcija (čita se, ne objavljuje).

## Granice (poznato, za kasnije)
- `ulaz.procitaj` za GitHub čita README; dublji uvid (fajlovi, kod, izdanja)
  je zaseban dovod.
- Stranice iza login-a / JS-render-a mogu da vrate prazan tekst → handler
  tada uredno staje („bez upotrebljivog teksta"), ne izmišlja.
- Sažetak je do 4000 znakova. „Napiši članak IZ sažetka" je sledeći korak
  (isti lanac: web.sazetak → content.draft).
