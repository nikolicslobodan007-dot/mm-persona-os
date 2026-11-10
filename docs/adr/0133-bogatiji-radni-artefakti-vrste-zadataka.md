# ADR-0133 — Bogatiji radni artefakti: vrste zadataka (stavka 2)

- **Status:** prihvaćen (10.11.2026.)
- **Povod:** Persona je do sada pravila samo kratku objavu (`service.draft`,
  hardkodirano „Napiši kratku objavu"). A u veštinama već ima znanje za bogatije
  artefakte. Živa proba battlecard-a potvrdila je i disciplinu: Mila je ODBILA da
  pravi battlecard sa izmišljenim brojkama (ADR-0033 + dosije firme: nemamo
  proizvod ni kupce) — dokaz da mehanizam vuče pravu veštinu i da agent poštuje
  „što nije izmereno nije tvrdnja". Ali i pouka: **sales-ops artefakti ne pašu
  Milinoj ulozi** (ona je content creator; firma nema pipeline). Zato joj dajemo
  CONTENT vrste koje može da ukoreni u javne izvore.
- **Prethodi:** ADR-0131 (promocija po domenu), ADR-0096/0112 (veštine u
  kontekstu), ADR-0033 (merenje), ADR-0074 (actor user:)
- **Menja:** nova `apps/content/zadaci.py` (registar), `apps/content/service.py`
  (`draft` prima `vrsta`), nova komanda `agent_zadatak.py`, testovi.

## Odluka

**Vrsta zadatka = (`upit`, `uputstvo`, `format`, `interni`).** Registar `ZADACI`;
`upit` sastavlja kontekst (ADR-0131 digne pravu veštinu sa koracima), `uputstvo`
kaže šta da napravi (`{ulaz}` = tema/konkurent/prospekt). Dve staze:

1. **CONTENT vrste** (objava→POST, dubinski-clanak→ARTICLE, nit→THREAD,
   newsletter→NEWSLETTER, video-scenario→VIDEO_SCRIPT) — javni sadržaj. Idu kroz
   **postojeći `service.draft`** (`draft(..., vrsta=z)`), pa se ČUVAJU kao
   `ContentItem` sa svim kapijama (zabrane, disclosure, repeticija, pravopis).
   Nema novog modela — poklapaju se sa `ContentFormat`.
2. **INTERNI artefakti** (battlecard, outreach, plan-naloga) — radni dokument koji
   se NE objavljuje na kanal. Zasad showcase: `agent_zadatak` ih ISPISUJE, ne čuva.
   Model `Artefakt` + pregled su sledeći sloj.

`draft` je proširen unazad kompatibilno: `vrsta=None` → staro ponašanje (kratka
objava, POST). Kad je `vrsta` data, koristi njen upit/uputstvo/format.

## Posledica
- `agent_zadatak --vrsta dubinski-clanak --ulaz "AI u B2B prodaji"` → pravi i čuva
  ContentItem (ARTICLE) kroz živ Gateway, sa Milinom disciplinom izvora.
- `agent_zadatak --vrsta battlecard --ulaz "..."` → showcase (radiće za agenta sa
  stvarnim pipeline-om i izvorom; za Milu/firmu bez proizvoda nema osnovu).
- Sledeći sloj: model `Artefakt` za interne; pa planer da agent sam bira vrstu po
  zadatku; pa — stavka 3 — prva prava akcija.
