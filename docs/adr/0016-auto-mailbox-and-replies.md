# ADR-0016 — Sandučić se otvara sam, agent piše nacrt odgovora

- **Status:** prihvaćeno
- **Datum:** 23.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §3.1, §9.1, §12.8 · ADR-0007, ADR-0008, ADR-0015
- **Kod:** `apps/channels/reply.py`, `apps/channels/mailbox.py`,
  `apps/personas/lifecycle.py`, `config/settings/base.py`,
  `apps/channels/management/commands/pilot_setup.py`, `tests/test_mail_reply.py`

## Kontekst

ADR-0015 je dao sandučić, ali se otvarao ručno — dugmetom ili komandom. Na
10.000 agenata to nije posao za čoveka (odluka Slobodana, 23.09.: „Neću da
otvaram 10.000 sandučića”). Drugo, pošta je stizala u bazu i tu stajala:
niko je nije čitao ni odgovarao na nju.

## Odluke

1. **Sandučić prati status persone.** Prelaz `DRAFT → READY` otvara sandučić,
   `→ ARCHIVED` ga gasi (Mailcow `active=0`, nalog u bazi `REVOKED`). Radi se
   posle potvrde transakcije (`transaction.on_commit`), pa nema sandučića za
   personu koja nije stvarno prešla u novi status.
2. **Kvar Mailcow-a ne ruši promenu statusa.** Greška ide u audit
   (`channel.mailbox.failed`) i vidi se na strani persone; status je promenjen.
   Otvaranje je idempotentno, pa ponovni pokušaj ne pravi duplikat.
3. **Sandučić dobija sposobnost `email.reply_inbound`** (isključena dok
   poverenje nije L2). Slanje i dalje traži odobrenje i otključan globalni
   prekidač — sposobnost sama po sebi ne šalje ništa.
4. **Nacrt odgovora.** Posle svakog čitanja pošte (beat na 120 s), za
   novopristigle poruke se pravi nacrt i predlaže akcija `mail.reply`. Nacrt
   ide kroz memoriju (`REPLY_CONTEXT`), model (`LLMPurpose.REPLY`), čišćenje
   teksta i tvrde zabrane, pa tek onda kroz policy. Rezultat je akcija koja
   **čeka odobrenje u konzoli**. Ništa ne izlazi napolje dok je
   `GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`.
5. **Kome se ne odgovara:** automatskim porukama (`Auto-Submitted`), listama
   (`List-Id`), pošiljaocima tipa `noreply@`/`postmaster@`/`mailer-daemon@`,
   porukama starijim od `MAIL_REPLY_MAX_AGE_HOURS` (72 h), istoj poruci
   dvaput, i kad persona nije `READY`/`ACTIVE` ili je sandučić ugašen.
6. **Plafon:** `MAIL_REPLIES_PER_DAY` (5) po agentu dnevno; preko toga se
   zapisuje `channel.mail.reply_skipped` sa razlogom `DAILY_CAP`.
   `MAIL_AUTOREPLY=false` gasi nacrte u celini, bez izmene koda.
7. **Greška jedne poruke ne ruši ostale** — svaka se obrađuje zasebno, kvar
   ide u audit (`channel.mail.reply_failed`).

## Zašto nacrt, a ne odgovor

Odgovor na poslovni mejl obećava rok, cenu ili uslov. Dok agent nema merenje
kvaliteta odgovora i dok je globalni prekidač zaključan, čovek potvrđuje svaki
odgovor. Kad se pokaže da nacrti prolaze bez izmena, ista akcija može da dobije
`ALLOW` kroz policy bez promene koda — menja se pravilo, ne modul.

## Posledice

- Nov agent dobija adresu čim pređe u `READY`, bez ijednog klika.
- Operater u konzoli vidi pristiglu poruku i pored nje nacrt odgovora koji
  čeka njegovo „da”.
- Rizik iz ADR-0015 ostaje: pre prvog slanja (GO) treba odvojiti IP/server za
  poštu agenata od MercatoMaster-a i BiznisPlanet-a.
- 419 testova (dodato 15).
