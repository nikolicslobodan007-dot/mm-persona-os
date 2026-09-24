# ADR-0015 — Sandučić za svakog agenta, na sopstvenom Mailcow-u

- **Status:** prihvaćeno
- **Datum:** 22.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §2, §12.8, §17 · Aneks A §6 · ADR-0008, ADR-0010
- **Kod:** `apps/channels/mailbox.py`, `apps/channels/tasks.py`,
  `apps/channels/management/commands/mailbox.py`, `config/settings/base.py`,
  `config/celery.py`, `console/` (kartica „Pošta”), `tests/test_mailbox.py`

## Kontekst

Agent koji radi umesto čoveka mora imati svoj mejl: za registracije, potvrde,
odgovore i upite. Razmatrane su tri mogućnosti.

- **Besplatni @gmail.com.** Otvaranje naloga traži proveru telefonom i CAPTCHA,
  koju ne zaobilazimo. Pravila Gmail-a zabranjuju više naloga radi zaobilaženja
  ograničenja, pa Google takve naloge masovno gasi. Nalog ne pripada nama. **Odbačeno.**
- **Google Workspace.** Oko 7 $ po korisniku mesečno, odnosno oko 70.000 $
  mesečno za 10.000 agenata. **Odbačeno zbog cene** (odluka Slobodana, 22.09.).
- **Sopstveni Mailcow.** Već radi na posebnom serveru za MercatoMaster i
  BiznisPlanet. Novi sandučić ne košta ništa, a Mailcow ima REST API. **Izabrano.**

## Odluke

1. **Svi agenti žive na `webkorporacija.com`** (odluka Slobodana, 22.09.).
   Adresa se pravi od imena, bez dijakritika i bez „(AI)”, na primer
   `mila.vukovic@webkorporacija.com`. Kada dva agenta imaju isto ime, drugi
   dobija broj iz svog ID-ja. U prikazanom imenu ostaje „Mila Vuković (AI)”.
2. **Adresa je za primanje i odgovore.** `webkorporacija.com` ostaje u
   `PRIMARY_COMPANY_DOMAINS`, pa je **hladna pošta sa njega i dalje zabranjena**
   (Canon §12.8 t.1). Hladna pošta, kad jednom bude potrebna, ide sa zasebnog
   `sending_domain`-a, uz najviše 3 sandučića po domenu i postepeno zagrevanje
   (ADR-0008). Odgovori (`mail.reply`) sa adrese persone idu kroz policy,
   odobrenje i obe brave.
3. **Sandučić otvara sistem** preko Mailcow API-ja (`POST /api/v1/add/mailbox`),
   iz konzole (dugme na strani persone) ili komandom `manage.py mailbox open`.
   Otvaranje je idempotentno. Dok je `MAILCOW_ENABLED=false`, ništa se ne upisuje
   ni u Mailcow ni u bazu.
4. **Tajne:**
   - Mailcow API ključ (Read-Write, dozvoljen samo IP našeg servera) je samo u
     `.env.prod`.
   - **Lozinka sandučića se ne čuva nigde.** Izvodi se kao
     `HMAC(MAILBOX_PASSWORD_SECRET, "mailbox:<ID>:v1")`. Promena te tajne menja
     sve lozinke, pa se tajna menja samo zajedno sa rotacijom u Mailcow-u.
   - U bazi je samo `credential_ref = "derived:mailbox:v1"`.
5. **Čitanje pošte:** beat na 120 s, red `mail` (`worker_channel`), IMAP na 993 (TLS).
   - Poruke ostaju na serveru, samo se označavaju kao pročitane.
   - U bazu ide `MailMessage`, jedinstven po `Message-ID`.
   - Tekst poruke se čuva 90 dana (`MAIL_BODY_RETENTION_DAYS`), a sama poruka bez teksta ostaje zauvek.
6. **Konzola:** kartica „Pošta” na strani persone prikazuje adresu, poslednjih
   10 pristiglih poruka i dugme „Otvori sandučić”.

## Rizik koji ostaje

Agenti i MercatoMaster/BiznisPlanet dele isti Mailcow server i istu IP adresu.
Primanje pošte ne kvari ugled. Pre prvog slanja (GO) treba odlučiti da li
agenti šalju sa zasebne IP adrese ili sa zasebnog servera, da problem jednog
agenta ne pogodi poštu drugih firmi.

## Posledice

- Novi agent dobija sandučić jednim klikom, bez troška i bez CAPTCHA.
- Kad se broj agenata poveća, isti adapter radi i sa drugim Mailcow serverom
  (npr. u sopstvenoj serverskoj sobi). Adrese ostaju iste.
- 404 testa (dodato 8).

## Dopuna 24.09. — kvota domena je granica broja agenata

Zapošljavanje prve ekipe (ADR-0028) prošlo je za svih 22 agenta, ali su
poslednja četiri ostala **bez sandučića**: u auditu stoji
`channel.mailbox.failed` umesto `provisioned`.

Uzrok je aritmetika, ne kvar. Domen agenata ima **20 GB ukupno**, a kvota po
sandučiću je bila **1 GB** — dvadeseti agent popuni domen, dvadeset prvi biva
odbijen. Mila i Jovan plus osamnaest novih je tačno dvadeset.

Tri izmene:

- **`MAILBOX_QUOTA_MB` je sada 200**, ne 1024. Agent prima poštu, ne arhivira
  je; 200 MB daje 100 agenata na istom domenu, koliko Pilot B i traži. Pre
  stotog agenta kvota domena se podiže u Mailcow-u.
- **Odbijanje zbog kvote dobija svoju poruku** (`MAILCOW_QUOTA`) umesto
  Mailcow-ovog nejasnog teksta: kaže koji je domen pun i šta da se uradi.
- **Ne prećutkuje se.** `manage.py mailbox bez` ispisuje ko nema sandučić,
  `mailbox popuni` otvara svima kojima fali (svaki zasebno — pad jednog ne ruši
  ostale), a `seed_ekipa` na kraju sam kaže koliko ih je ostalo bez.

Ovo je prvo mesto na kom se videlo da neka granica ne skalira sa brojem
agenata. Neće biti poslednje — zato je i zapisano ovde, a ne samo popravljeno.

