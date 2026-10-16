# ADR-0107 — Agent zna gde radi

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Posle ADR-0106 direktor treba da od poruke napravi nalog. Čovek je
  na to odgovorio tačno: *„NE MOŽE DA NAPRAVI KADA NE ZNA NIŠTA!"* Agent zna ko
  je on (dosije persone, ADR-0017), ali ne zna **gde radi**.
- **Prethodi:** ADR-0096 (paket znanja), ADR-0105, ADR-0106
- **Menja:** `firma/dosije.md` (novo), `apps/memory/context.py`,
  `apps/orchestration/razgovor.py`, `tests/test_memory.py`
- **Canon:** §17 (oznaka AI), §9.4 (tvrde zabrane)

## Povod, tačnije

Vlasnik je pokazao `SYSTEM PROMPT` koji je napisao za Kolibicu: šta brend
radi, po čemu je poznat, ko su kupci, šta publika vrednuje, kako se piše i šta
se ne radi. Agent koji to pročita ume da napravi nalog. Za Web Korporaciju
takvog teksta **nije bilo nigde** — ni u kodu, ni u bazi, ni u promptu.

## Odluka

**1. Dosije firme je jedan fajl u repozitorijumu** — `firma/dosije.md`. Ne u
bazi: piše ga čovek, menja se kroz izmenu koja prolazi kapije, i u istoriji se
vidi ko ga je i kada promenio.

**2. Ulazi u paket svakog agenta**, odmah iza toga ko je agent, a pre stanja,
zadatka, pravila i veština. Redosled nije ukras: bez njega agent izmišlja
kupce, cene i usluge kojih nema.

**3. Sadržaj je vlasnikov, ne naš.** Zapisano je ono što je rekao:

- firma trenutno radi **isključivo za vlasnika**; nema spoljnih kupaca,
  pretplate ni cenovnika;
- radi ono što vlasnik ne stigne ili ne ume, i taj posao mu je vredan;
- obećanje: *kada vlasnikov problem dođe do Ivane, ona ga rešava sa ostalim
  agentima*;
- nikad: kocka, pornografija, krađa i objava tuđeg kao svog, prevare,
  prostitucija, droga, zlato, oružje.

**4. Ono čega nema u dosijeu se ne izmišlja.** To stoji kao prva rečenica
dosijea, jer je najčešći način da agent slaže — da popuni prazninu nečim što
zvuči dobro. Firma bez cenovnika ne sme da dobije cenovnik iz modela.

**5. Direktor dobija dosije i kad pravi nalog** (ADR-0106), ne samo kroz
paket: procena se dešava pre nego što iko sastavi paket.

**6. Bez fajla sve radi kao pre.** Odeljak je prazan, paket se gradi, ništa ne
puca. Za to postoji test.

## Cena, merena

Dosije je ~317 reči. Ulazi u **svaki** paket, pa troši deo plafona koji bi
inače pripao memoriji. To je svesno: agent koji zna gde radi troši manje na
ispravljanje nego što bi uštedeo na tokenima. Kad dosije poraste preko jedne
stranice, ovo se ponovo meri.

## Šta ovo NE radi

- **Ne zamenjuje dosije persone** (ko je agent) ni prirucnik radnog mesta.
- **Nije cenovnik ni katalog usluga** — kad ih bude, biće svoj fajl i svoja
  odluka.
- **Ne govori agentu kako da piše** — ton i pravila pisanja su `EditorialLesson`
  i Rečnik, ne ovaj dosije.
