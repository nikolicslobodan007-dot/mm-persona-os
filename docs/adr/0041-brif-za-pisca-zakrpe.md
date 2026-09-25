# ADR-0041 — Brif za pisca zakrpe

- **Status:** prihvaćen (25.09.2026.) — **prva polovina**; petlja pisanja je odvojena
  odluka i čeka izbor modela i plafona troška
- **Prethodi:** ADR-0038 (zakrpa kao kapija), ADR-0039 (tri tačke), ADR-0040 (red),
  ADR-0035 (model zadatka), ADR-0033 (pravilo nula)

## Problem

Lanac od zakrpe do kapija radi i izmereno je da meri pravo stablo. Ali **niko ne piše
zakrpu.** Do sada ju je kucao čovek.

Da bi je napisao agent, mora da vidi fajlove kakvi su sada. Toga nema nigde:
`/tasks/{id}/work` daje zakrpu koja **postoji**, a ne građu za zakrpu koja tek treba
da nastane.

## Odluka

`GET /tasks/{id}/brief` vraća sve što piscu treba i ništa više: zadatak i razlog,
dozvoljene putanje, tražene kapije, **sadržaj fajlova pod tim putanjama**, spisak
zaštićenih zona, otvorene nalaze recenzenta i poslednje pale kapije.

### 1. Brif staje u granice, i kaže šta je odsekao

Najviše 40 fajlova, 60 KB po fajlu, 200 KB ukupno. Zadatak koji to probija nije uzak
dovoljno — **deli se, ne podiže se plafon.**

Ono što je izostavljeno ide u `truncated`, sa razlogom po stavci. Ovo nije kozmetika:
pisac koji ne zna da nije video sve piše zakrpu nad pretpostavkom, a to je tačno ono
što ADR-0033 zabranjuje. Prazan brif je uredan ishod kad su sve putanje zaštićene — i
tada mora da bude **objašnjen**, ne prećutan.

### 2. Otisak po fajlu umesto commita

Slika aplikacije nema `.git`, pa brif **ne može** da tvrdi nad kojim je commit-om
nastao. Umesto obećanja koje ne može da ispuni, daje `sha256` po fajlu. Ako se radni
primerak razlikuje, `git apply` pukne glasno — a to je bolje od tihe zakrpe nad
zastarelim sadržajem.

### 3. Zaštićena zona se ne prikazuje, ni slučajno

Fajl u zaštićenoj zoni se ne šalje čak ni kad se nađe pod dozvoljenim prefiksom;
upisuje se u `truncated` sa razlogom. Zona se ne otvara ni čitanjem.

### 4. Povratna informacija ide uz brif

Otvoreni nalazi i poslednje **pale** kapije, sa ispisom. Bez toga bi sledeći pokušaj
ponovio istu grešku, a petlja bi trošila novac na krug u mestu.

## Šta je odbačeno

- **Ceo repozitorijum u prompt.** Skupo, sporo, i suprotno svemu što je ADR-0035
  postavio o uskim zadacima.
- **Tvrdnja o commit-u** koju slika ne može da potkrepi.
- **Tiho sečenje** — spisak bez razloga je isto što i laž o potpunosti.
- **Da brif nosi i predlog rešenja.** Brif je građa; predlog je posao pisca.

## Šta ostaje otvoreno (druga polovina)

Petlja pisanja: model napiše diff → `zakrpa.check` → kapije → ako padne, ishod se
vraća modelu. Tri brojke koje pre toga moraju da se odluče, i sve tri su poslovne, ne
tehničke:

- **koji model piše kod** (Sonnet 5 je izmeren na nacrtima, ne na kodu; jeftin model
  koji ne trenira je kandidat, ali neizmeren);
- **plafon troška po zadatku**, u centima, koji se ne prelazi;
- **najviše iteracija** i prekidač „nema napretka" (OpenHuman beleške, 24.09.).

Agent koji stane sa „nisam uspeo u okviru budžeta" je ispravan ishod. Agent koji melje
tri sata nije.

## Posledice

- `apps/orchestration/brif.py`, `GET /tasks/{id}/brief`, ugovor regenerisan.
- `tests/test_brif.py`: 19 provera.
- Nalaz iz pisanja testova: `tools/` sadrži samo `canon_lint.py`, koji je zaštićen, pa
  je brif nad njim s pravom prazan. Test je bio napisan na pretpostavci da tamo ima i
  drugih fajlova — greška je bila u testu, ne u kodu, i to je sada zasebna provera.
