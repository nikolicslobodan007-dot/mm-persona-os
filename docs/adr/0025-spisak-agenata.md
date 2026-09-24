# ADR-0025 — Spisak agenata

- **Status:** prihvaćen
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0010 (konzola), ADR-0019 (konzola v2), ADR-0017 (organizacija)

## Problem

Bočni meni „Agenti" vodio je na **`/console/personas/P-00001`** — na Milu.
To je radilo dok je firma imala jednog agenta. Sa dva već nije: drugi se nije
video nigde osim preko strane Organizacija. Sa deset hiljada bi bilo besmisleno.

Uz to, strana jednog agenta se skrolovala bez kraja — kartice su bile nabacane
jedna ispod druge iako tabovi postoje od ADR-0019.

## Odluka

**`/console/personas` je spisak**, a strana pojedinačnog agenta je ono što se
otvara iz njega.

### Pretraga i filteri

Pretraga gleda ono po čemu čovek zaista traži: **ime, broj agenta, adresu
sandučića, korisničko ime naloga, radno mesto i sektor**. Uz nju dva filtera,
da se „svi u marketingu" ne mora kucati: **sektor** i **status**.

Pretraga po radnom mestu gleda **samo tekući raspored** — ko je nekad bio
urednik ne izlazi na upit „urednik". Istorija rasporeda postoji (ADR-0017),
ali pretraga pita gde neko radi **sada**.

### Spisak podnosi 10.000

Strana ima 40 redova (`PO_STRANI`) i listanje. Kolone koje traže podatke iz
drugih tabela — radno mesto, šef, šta čeka, poslednje buđenje — rade se **u
jednom upitu po koloni**, ne u jednom po agentu. Spisak od 40 agenata je
šest upita, koliko i spisak od jednog.

Kolona „Odgovara" pokazuje šefa iz organizacije; kolona „Čeka" je broj
odobrenja koja stoje na tom agentu i vodi pravo na Odobrenja.

### Strana agenta

Kartica „Radno mesto" ulazi u istu mrežu sa stanjem i statusom, pa se cela
kartica „Stanje" vidi bez skrolovanja. „Buđenja" su dnevnik rada, ne trenutno
stanje — sele se u karticu „Akcije", ispod planova. Na vrhu strane stoji
povratak na spisak.

### Sličica i označavanje

Red počinje **profilnom slikom** agenta; ko je još nema, dobija slovo u krugu —
lice je najbrži način da se u spisku od hiljadu redova nađe pravi agent.

Uz sliku ide i **kućica za označavanje**, pa se ista radnja radi nad više
agenata odjednom: za sada „Aktiviraj" i „Pauziraj", a spisak radnji
(`MASOVNE_AKCIJE`) je jedno mesto u kodu i raste kad zatreba.

Masovna radnja **ne daje nijedno novo pravo**: svaki agent prolazi kroz isti
`lifecycle.change_status`, istu tabelu prelaza i istu ulogu kao da si ga
otvorio pojedinačno. Razlog je obavezan i ide u audit. Ko ne sme da pređe —
preskače se, i u poruci stoji **zašto**, po agentu. Najviše 200 agenata po
radnji, kao brana od promašenog „označi sve".

## Šta je odbačeno

- **Beskonačno skrolovanje umesto listanja.** Operater koji traži jednog
  agenta ne skroluje deset hiljada redova; on ga potraži.
- **Pretraga koja gleba i arhivirane rasporede.** Vraćala bi ljude na mesta
  na kojima više nisu.
- **Kolona sa poverenjem u spisku.** Poverenje ide po capability-ju, pa jedan
  broj po agentu ne postoji — pokazivati „nivo agenta" bi bila laž (Canon §3.11).
- **Masovno arhiviranje i brisanje.** Arhiviranje je trajno (Canon §3.1);
  trajna radnja nad stotinu agenata jednim klikom nema dovoljno dobar razlog.
- **„Označi sve" preko svih strana.** Kućica označava samo ono što se vidi;
  označavanje nevidljivog je najbrži put do nesreće.

## Posledice

- Novi agent je vidljiv onog trenutka kad je zaposlen, bez znanja njegovog broja.
- Otvoreno: sortiranje po kolonama i izvoz spiska; dolaze kad zatrebaju.

## Kod

- `console/views.py` — `personas()`, `personas_bulk()`, `_red_spiska()`,
  `PO_STRANI`, `MASOVNE_AKCIJE`, `MASOVNO_NAJVISE`
- `console/templates/console/personas.html`
- `console/templates/console/persona.html` — povratak, preraspodela kartica
- `console/static/console/console.js` — označavanje svih na strani
- `tests/test_console.py::TestSpisakAgenata`, `::TestMasovnaAkcija` (11 provera)
