# ADR-0158: Telegram prima sliku (ADR-0118 na Telegram ulazu)

Status: Prihvaćeno · Datum: 2026-11-14

## Kontekst

Telegram most (ADR-0134) v1 je obrađivao SAMO tekst: `obradi_batch` je čitao
`msg["text"]`, a poruku bez teksta tiho preskakao. Kad vlasnik pošalje Ivani
sliku uz pitanje „Šta je ovo?", poruka je ispadala kroz `if not telo: continue`
— bot ne bi odgovorio. Docstring je to i najavljivao: „prilozi kasnije".

Ceo NIZVODNI lanac već podržava slike (ADR-0118): `razgovor.posalji(..., media=...)`
→ `razmisli` → `gateway.generate(..., media=...)`, a gejtvej šalje vizuelni blok
spoljnoj ruti (ili napomenu kad nema vision rute). Konzola već prima sliku preko
`_obradi_priloge` (snima `MediaAsset`, `origin=user_owned`). Falio je samo Telegram
ulaz.

## Odluka

Dogradi Telegram ulaz da prepozna i prosledi sliku — isti obrazac kao konzola:

- `obradi_batch`: `telo` je sada `text` ILI `caption`; `_slika_iz(msg)` vadi
  najveću sliku (`photo[-1]`, uvek JPEG) ili `document` sa `image/*` mime-om;
  uslov preskoka je „ni teksta ni slike". `file_id` + mime idu u task.
- `preuzmi_sliku(file_id)`: `getFile` → `file_path` → download sa file-API-ja,
  granica 5 MB (ADR-0118), svaki pad se guta (vraća None, ne ruši odgovor).
- `telegram_odgovori(..., foto_file_id, foto_mime)`: skine sliku, sačuva kao
  `MediaAsset` (`PHOTO`, `origin=user_owned`, persona = direktor DIR-00) i pozove
  `razgovor.posalji(..., prilozi=..., media=...)`. `prilozi` je tu i da poruka
  bez teksta (samo slika) ne padne na „Prazna poruka" i da se prilog vidi u niti.

Vision i dalje traži spoljnu rutu (ADR-0118 §5): bez nje agent dobije napomenu da
je slika stigla, ali je ovim putem ne vidi — pošteno, bez izmišljanja (ADR-0033).
Ivana (Gemini ruta) vidi.

## Van obima

Zvuk/glasovne poruke (ADR-0078 ostaje zaseban), video, više slika po poruci
(Telegram album = više update-ova; za sada se obrađuje po jedna). Webhook umesto
polling-a.

## Posledice

- Izmenjeni `apps/channels/telegram.py` (+`_slika_iz`, +`preuzmi_sliku`, caption),
  `apps/channels/tasks.py` (+`_slikovni_prilog`, task prima sliku).
- +`tests/test_telegram_slika.py`.
- Aditivna promena: poruka bez slike ide istim putem kao pre.
