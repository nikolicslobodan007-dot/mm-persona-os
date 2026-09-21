# ADR-0010 — F8: Kontrolna tabla (konzola) sa drugim faktorom

- **Status:** prihvaćeno
- **Datum:** 21.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §8.1, §9.6, §15, §17, §18
- **Kod:** paket `console/` (views, auth, totp, šabloni, statika), migracija `console 0001`,
  `config/settings/base.py`, `tests/test_console.py`

## Kontekst

Posle F7 Mila sama stavlja nacrte u red za odobravanje, a odobrenje važi 2 h.
Odobravanje preko curl-a na serveru nije održivo. Operateru treba jedno mesto
za pet stvari:

- odobravanje, izmenu i odbijanje objava;
- zaustavljanje (kill-switch) i puštanje;
- pregled persone: stanje, buđenja, sadržaj, akcije;
- tačan zapis šta bi otišlo napolje;
- trošak i incidente.

## Odluke

### 1. Putanja `/console/` — dopuna Canon §8.1

Canon kaže „sve pod `/api/v1/`, van toga samo `/healthz` i početna strana".
Konzola je HTML za ljude, a ne API. Dodaje se ovim ADR-om kao treći izuzetak.
Početna strana i dalje ne otkriva ništa i ne vodi na konzolu.

### 2. Paket `console/` van `apps/`

Canon §1 propisuje tačno dvanaest domenskih app-ova. Konzola nije domen nego
prikaz nad domenima, isto kao `api/`. Zato je `console` Django app van `apps/`,
bez sopstvenih pravila.

**Svaki upis ide kroz isti servisni sloj kao API** (`policy.decide_approval`,
`activate_kill_switch`, `release_kill_switch`), uz
`bind(actor_id="user:<ime>")`. Isti audit, isti akter i iste provere važe bez
obzira na to da li je odluka došla iz konzole ili preko API-ja.

### 3. Prijava: lozinka + TOTP, bez izuzetka

- Prvi korak je korisničko ime i lozinka. Posle njega **ne postoji sesija**,
  samo privremena oznaka u sesiji da se čeka kod.
- Drugi korak je šestocifreni kod (RFC 6238, SHA-1, 30 s), koji radi sa svakom
  aplikacijom za kodove. Tek posle njega nastaje prijava.
- **Tajna TOTP-a se ne čuva u bazi** (Canon §2, §17). Izvodi se iz
  `HMAC(SECRET_KEY, "console-totp:<korisnik>:<verzija>")`. U bazi su samo
  verzija ključa, vreme potvrde i poslednji iskorišćeni korak.
- Rotacija: `console_totp --user X --rotate` povećava verziju i stari ključ
  odmah prestaje da važi. Promena `DJANGO_SECRET_KEY` poništava sve ključeve.
- **Isti kod se ne prima dvaput** (`last_step`), a prozor je ±1 korak (±30 s).
- Ključ se uključuje **samo na serveru** (`manage.py console_totp`). Nikad se
  ne prikazuje u pregledaču. Nalog bez uključenog drugog faktora ne ulazi.
- Pet promašaja po paru (IP, korisnik) daje 15 minuta pauze. Važi i za lozinku
  i za kod, a brojač je u Redis kešu.
- Ulaze samo korisnici sa bar jednom Canon ulogom (ili superuser).

### 4. Ovlašćenja po radnji, ne po strani

| Radnja | Uslov |
|---|---|
| Gledanje | bilo koja uloga |
| Odobri / izmeni / odbij | dozvola `policy.decide_approval` |
| Zaustavi (kill-switch) | sve uloge osim `viewer` |
| Pusti | `trust_safety`, `runtime_admin`, `system_admin` |

Odbijanje traži razlog. Izmenjen tekst prolazi iste tvrde zabrane kao i
predlog, pa zabrana koju unese odobravalac znači SEV1 i suspenziju (ADR-0007 §3).

### 5. Zaštite na ivici

- CSRF na svakom formularu. API je i dalje `csrf_exempt` (token, DRF).
- `SameSite=Strict` za sesiju i CSRF kolačić; u produkciji `Secure`.
- Sesija traje 8 h.
- Stroga CSP: samo `'self'`, bez inline skripti i stilova, uz
  `frame-ancestors 'none'`, `form-action 'self'` i `base-uri 'none'`.
- `Cache-Control: no-store` i `X-Robots-Tag: noindex` na svakoj strani.
- `next` posle prijave vodi samo unutar `/console`.

### 6. Oblik

- Server renderuje HTML (Django šabloni), sa jednim CSS i jednim malim JS fajlom
  (odbrojavanje isteka, potvrda pre zaustavljanja, prikaz formi za izmenu i
  odbijanje) i bez spoljnih biblioteka.
- Svetla i tamna tema prate sistem.
- Vreme se prikazuje u Europe/Belgrade.
- Pregled se osvežava na 60 s. Odobrenja se **ne** osvežavaju sama, da izmena
  teksta ne bi nestala.

Strane:

- **Pregled:** red odobrenja, sadržaj za 24 h, izvršenje, trošak meseca,
  kill-switch, persone, incidenti i poslednje akcije.
- **Odobrenja:** pun tekst, kanal, klasa, rizik, razlozi i odbrojavanje do
  isteka; dugmad Odobri, Izmeni pa odobri, Odbij.
- **Persona:** stanje, poverenje, nalozi, memorija, buđenja, sadržaj i akcije.
- **Sadržaj:** filter po statusu i objave po kanalu.
- **Akcija:** odluke, odobrenja i pokušaji, sa zapisom zahteva koji bi otišli napolje.
- **Troškovi** (30 dana, po vrsti i personi) i **Incidenti**.

### 7. Podešavanja pomerena u base

Sesije, poruke, statika, CSRF, šabloni i `X-Frame-Options` bili su samo u
`prod.py`. Pomereni su u `base.py`, pa ih testovi vide isto kao produkcija.
U `prod.py` je ostalo samo ono što važi iza HTTPS-a (`Secure` kolačići, proxy
zaglavlje, `STATIC_ROOT`).

## Šta F8 namerno ne radi

- **Keycloak/OIDC** (Canon §18) — za jednog operatera je TOTP dovoljan; SSO dolazi sa timom.
- **Menjanje poverenja i pravila iz konzole.** To ostaje svesno teža radnja (API ili komanda).
- **Potvrda incidenata**, uređivanje persone i ručno pravljenje nacrta iz konzole.
- **Obaveštenja** (mejl/telefon) kad nešto čeka odobrenje.

## Posledice

- Migracija `console 0001` (`OperatorTOTP`).
- Pre prvog ulaska na serveru se jednom pokreće `console_totp --user <ime>`.
- 367 testova (F8 dodaje 18).
