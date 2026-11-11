# ADR-0136 — Rutiranje zadatka po vrsti: „prepiši video" ide na ASR

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Živa proba (Telegram): „pregledaj video, pokupi titlove, napiši
  prepis" → direktor je delegirao, ali izvršilac je uvek zvao `content.draft`
  („napiši objavu o temi"), pa je rezultat bio generička objava, ne prepis.
  Delegacioni lanac je svaki zadatak pretvarao u pisanje.
- **Prethodi:** ADR-0105/0106 (razgovor, procena), ADR-0125 (klip ASR),
  ADR-0078 (TRANSCRIBE), ADR-0135 (istorija niti)
- **Menja:** `apps/orchestration/razgovor.py` (razmisli vraća `vrsta`+`url`,
  `_koraci` rutira, `_ishod` vadi prepis), `apps/orchestration/plans.py`
  (HANDLER_MODULES), nova `apps/memory/veritas/steps.py` (handler `klip.prepis`),
  testovi.

## Odluka
**Direktor bira TIP zadatka, lanac zove pravu sposobnost.** `razmisli` uz
`sektor/nalog` sada vraća i `vrsta` (`objava` | `prepis-videa`) i `url`. Kad je
vrsta `prepis-videa` i ima url, `_koraci` gradi lanac sa handlerom **`klip.prepis`**
umesto `content.draft`. Handler zove postojeću kapiju `klip.transkribuj(url)`
(yt-dlp → ffmpeg → Gateway TRANSCRIBE, ADR-0125) i vraća prepis; `_ishod` ga
pošalje čoveku kao rezultat. `objava` ostaje kao pre (content.draft).

Time se agent od „pisca objava" pretvara u nekog ko zove stvarnu veštinu po
tipu posla. Obrazac je proširiv: nove vrste → novi handleri (pretraga, itd.).

## Granice (poznato, za kasnije)
- **FB reel** često traži login/cookies za yt-dlp — baš taj izvor može da ne
  skine. YouTube/X/javni linkovi rade. FB-specifično vađenje je zaseban dovod.
- Prepis se vraća sirov (do 4000 znakova na Telegramu). „Napiši članak IZ
  prepisa" je sledeći korak (prepis → content.draft u istom lancu).
- Rutiranje zasad pokriva `prepis-videa`; ostali tipovi (pretraga, analiza)
  dolaze istim obrascem.

## Posledica
„Prepiši ovaj video" sada stvarno ide na ASR i vraća prepis, a ne generičku
objavu — za izvore koje yt-dlp ume da skine.
