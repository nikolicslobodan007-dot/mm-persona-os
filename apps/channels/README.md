# apps/channels

ADR-0043: ovaj README postoji da se granica prema `apps/content` ne izvodi
iz koda svaki put iznova.

## Odgovornost

`apps/channels` vodi **naloge** preko kojih persona ili brend izlazi na
spoljni svet i njihove tehničke mogućnosti:

- `ChannelAccount` — nalog koji persona legitimno kontroliše (tip kanala,
  identitet-nosilac, status, disclosure, polja odlazne pošte).
- `ChannelCapability` — šta je na tom nalogu stvarno moguće (Canon §12.1:
  `CAPABILITY_UNAVAILABLE` je validan ishod, ne greška).
- `IntegrationEndpoint` — konfiguracija provider adaptera, bez ijedne tajne.
- `MailMessage` — normalizovana koverta dolazne i odlazne pošte (Canon §1,
  §12.8), i logika oko nje: sandučić (`mailbox.py`), nacrt odgovora
  (`reply.py`), lista odjava (`suppression.py`).

Ukratko: **ko sme da priča, gde, i kao ko** — nalog, kanal, capability,
disclosure, sandučić pošte.

## Šta NIJE ovde (granica prema `apps/content`)

`apps/content` vodi **šta se kaže**: ideje, nacrti, format, status odobrenja
i zakazivanja objave (`ContentStatus`, `ContentFormat`, `PublicationStatus`).

Praktično pravilo: ako pitanje glasi "da li ovaj nalog sme ovo da uradi" —
odgovor je u `channels`. Ako pitanje glasi "šta piše u objavi i da li je
odobrena" — odgovor je u `content`. `MailMessage` je izuzetak koji ostaje u
`channels` jer je pošta kanal (vlasništvo, autentikacija, retencija), a ne
sadržajna jedinica koja prolazi kroz uređivački tok.

## Zavisnosti

- `apps.personas` — nalog pripada personi.
- `apps.orchestration` — `MailMessage.action`, plan "napiši pa pošalji"
  (ADR-0021).
- `apps.policy` — provera pre slanja (`policy.propose`, `guards`).
- `apps.runtime` — `BrowserProfile`, secret store (`resolve_secret`).
- `api.audit` — svaki upis ide uz audit zapis u istoj transakciji.

Kanonski dokumenti: Canon §1, §3.14–3.16, §12.8, §16; ADR-0007, ADR-0008,
ADR-0010, ADR-0015, ADR-0016, ADR-0021, ADR-0043.
