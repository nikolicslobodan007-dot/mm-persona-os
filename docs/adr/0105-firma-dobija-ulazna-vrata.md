# ADR-0105 — Firma dobija ulazna vrata

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Svaki posao u ovoj firmi do danas je počinjao komandom u
  terminalu, koju je čoveku morao neko da napiše. Konzola je pokazivala šta su
  agenti uradili, ali čovek nije imao gde da kaže šta treba.
- **Prethodi:** ADR-0010 (konzola), ADR-0017 (organizacija), ADR-0022
  (delegiranje), ADR-0024 (koraci sadržaja)
- **Menja:** `apps/orchestration/models.py` (+ migracija `0013`),
  `apps/orchestration/razgovor.py` (novo), `console/views.py`,
  `console/urls.py`, `console/templates/console/razgovor.html` (novo),
  `console/templates/console/base.html`
- **Canon:** §15.2, §3.11

## Izmereno pre odluke

Sve što treba za lanac **već postoji** i radi: `plans.start`, obrađivač
`org.delegate`, povratak posla nalogodavcu (`_resume_parent`), granica dubine
`MAX_DELEGATION_DEPTH = 3`. Izmereno iste večeri: lanac
direktor → šef → izvršilac prolazi za oko desetak sekundi i vraća nacrt.

Falio je samo ulaz. Zato ovo nije nov podsistem nego dve tabele, jedan servis
i jedna stranica.

## Odluka

**1. Nit razgovora (`Razgovor`) i poruka (`Poruka`).** Nit je između čoveka i
**jedne** persone — direktora (radno mesto `DIR-00`). Tako je čovek i
zamislio firmu: priča sa jednim agentom, a taj spušta posao niz lanac.

**2. Nit nije kanal.** Ovo je unutrašnji razgovor sa vlasnikom sistema, ne
poruka napolje: ne prolazi kroz `ChannelAccount`, nema oznaku objave i ne dira
prekidač spoljnih radnji. Objava i pošta ostaju zasebna vrata sa svojim
odobrenjima.

**3. Poruka nosi plan.** `Poruka.plan` je veza ka poslu koji je ta poruka
pokrenula. Bez nje bi nit bila ćaskanje, a ne nalog: u niti se vidi i šta je
traženo i šta je urađeno, sa brojem plana.

**4. Delegiranje i dalje ne daje nijednu dozvolu** (ADR-0017). Direktor ne
dobija ništa time što je direktor; izvršilac radi sa svojim poverenjem. Za to
postoji test koji upoređuje poverenje svih persona pre i posle naloga.

**5. Razvrstavanje po sektorima je zasad tabela reči.** Poređenje ide nad
`embeddings.normalize`, pa dijakritika i velika slova ne smetaju; bez pogotka
posao ide UPRAVI, jer direktor ima asistenta. **Ovo je privremeno i tako je i
napisano u kodu** — kad direktor bude birala sektor modelom, menja se samo
`odredi_sektor`. Nije upisano kao trajno rešenje da se kasnije ne bi branilo
kao odluka.

**6. Posao se izvršava u istom zahtevu.** Čovek pošalje poruku i čeka
odgovor. Dok lanac traje desetak sekundi, to je bolje nego da ekran ćuti.
Kada lanci postanu duži, posao ide u red i nit se osvežava — tada se menja
samo poziv `plans.advance`.

**7. Akter je čovek.** `console_view` već vezuje `bind(actor_id=...)`, pa
audit ovog puta nosi prijavljenog čoveka, a ne `service:system`. To je ista
rupa koja je izmerena večeras na pravljenju dokumenta iz ljuske.

## Šta ovo NE radi

- **Nema priloga.** Čovek zasad šalje tekst; fajl, link i slika su sledeći
  korak i traže svoja pravila o izvoru i licenci.
- **Direktor ne razmišlja.** Ona razvrstava i zadaje; ne procenjuje da li
  posao uopšte ima smisla, ne traži dopunu i ne odbija glupost. To je sledeća
  odluka i tiče se njenog prompta, ne ovog lanca.
- **Srednji nivo je i dalje poštar.** Šef zada izvršiocu i preuzme gotovo;
  ne pregleda i ne vraća na doradu. `plan.note` i dalje doslovno ne radi
  ništa, i to ostaje otvoreno.
- **Jedna nit po čoveku**, bez arhive i pretrage.
