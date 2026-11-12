# ADR-0147 — Dug sadržaj ide i kao PDF na Telegram (dostava)

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Formatiran izlaz (Slajs 2). Motor za PDF je živ (ADR-0146), ali
  Ivana je umela da pošalje samo tekst (`sendMessage`). Vlasnik hoće da dug
  sadržaj (članak/analiza) dobije i kao **fajl koji može da otvori i prosledi**.
- **Prethodi:** ADR-0146 (LibreOffice u slici), ADR-0103 (nacrt → fajl),
  ADR-0134 (Telegram most).
- **Menja:** `apps/channels/telegram.py` (nova `posalji_dokument` = sendDocument
  multipart), `apps/channels/tasks.py` (`_mozda_dokument` posle odgovora).

## Odluka
Posle tekstualnog odgovora na Telegramu, ako je rezultat **dug format**
(`ARTICLE` ili `NEWSLETTER`), lanac napravi **PDF** od finalnog (revidiranog,
pregledanog) nacrta i pošalje ga kao fajl uz tekst. Kratki formati (objava,
nit) ne idu kao fajl — tekst je dovoljan.

- `posalji_dokument(chat_id, podaci, naziv, opis)` — sendDocument preko
  multipart/form-data; naziv fajla je naslov nacrta + `.pdf`.
- `_mozda_dokument(chat_id, odgovor)` — čita `odgovor.delovi["item"]` (finalni
  ContentItem, ADR-0144), proverava format, pravi PDF (`dokument.napravi`),
  vuče bajtove iz skladišta i šalje.

**Fajl je dodatak, ne sme da obori odgovor.** Svaki pad (nema LibreOffice u
radniku, skladište, mreža) se guta uz upozorenje; tekst je već poslat.

## Posledice
- Članak/analiza stiže i kao PDF — korak ka onom ChatGPT-ovom dokumentu.
- Radnici (worker_channel) sada moraju imati LibreOffice (ADR-0146): deploy
  podiže SVE servise (`up -d`), ne samo `web`.

## Granice (za kasnije)
- Za sada samo ARTICLE/NEWSLETTER → PDF. „Pošalji kao PDF" na zahtev za bilo
  koji format i PDF za web-sažetak (nije ContentItem) su zaseban korak.
- Word/Excel su u motoru (ADR-0146); dostava zasad šalje PDF.
