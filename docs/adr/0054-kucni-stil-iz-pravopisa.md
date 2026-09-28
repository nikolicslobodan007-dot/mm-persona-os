# ADR-0054 — Kućni stil iz Pravopisa, sa brojem tačke

- **Status:** prihvaćen (28.09.2026.)
- **Prethodi:** ADR-0014 (pouke urednika), ADR-0017 (tri nivoa pouke), ADR-0033
- **Menja:** ADR-0014 — pouka od sada može da nastane i iz knjige, ne samo iz odluke
  urednika nad nacrtom

## Šta se desilo

U folderu „PDF Za AI Agente" tri dana je stajao skeniran *Pravopis srpskoga jezika*
Matice srpske. Nijedno pravopisno pravilo nije bilo upisano nigde u sistem. Svi
agenti koji pišu srpski pisali su ga po tome kako model pretpostavlja da srpski
izgleda — a model sistematski greši na istim mestima: futur po hrvatskom obrascu
(`znat ću`), engleski navodnici (`"ovako"`), crta umesto crtice.

To nije bila nepoznanica. Pravopis je bio na disku, a pravilo o futuru staje u jedan
red. Nedostajalo je mesto u kojem takvo pravilo živi.

## Odluka

### 1. `apps/content/pravopis.py` — pravila prepisana iz knjige, sa tačkom

Šest pravila, svako sa `kljuc`, `tekst`, primerom `pre`/`posle` i **brojem tačke**:

| ključ | tačka | o čemu |
|---|---|---|
| `futur-sazeti` | 63a | `znaću`, ne `znat ću`; glagoli na -ći se ne sažimaju |
| `enklitike-odvojeno` | 63a | `on je znao`, `znao bi` — odvojeno |
| `negacija-ne` | 63b | `ne zna` odvojeno; `nepisan`, `nemoj` spojeno |
| `rečca-li` | 63c | `da li`, `znaš li` — uvek odvojeno |
| `navodnici` | 208 | srpski `„ovako"` ili `»ovako«`, nikad `"ovako"` |
| `crta-i-crtica` | 217 | crtica primaknuta, crta sa razmacima |

Broj tačke ide u sam prompt: `(Pravopis, t. 63a)`. Pravilo bez izvora je tvrdnja
koju niko ne može da potkrepi, a takvu ADR-0033 ne prima — ni od agenta, ni od mene.
Kad model napiše `znat ću` i neko pita zašto je odbijen, odgovor je broj tačke, ne
moje mišljenje o srpskom.

**Pismo:** agenti pišu latinicom sa svim dijakriticima, pa su primeri takvi. Izvornik
ostaje ćirilični; pravila o slovima (`in-j` naspram `nj`) se ne prevode jer preslovljena
gube smisao, ali šest odabranih važe u oba pisma.

**Zašto baš ovih šest:** nisu odabrana po tome koliko su zanimljiva, nego po tome
koliko često izlaze na videlo u tekstu koji model napiše. Test to i proverava
(`test_pravila_nose_broj_tacke`, `test_primeri_su_u_latinici_sa_dijakriticima`).

### 2. `lessons.upisi_kucni_stil()` — idempotentno **po ključu**, ne po tekstu

Pravila se upisuju kao `EditorialLesson` sa `persona=NULL, department=NULL` — kućni
stil firme po ADR-0017, važi za sve agente, i za one koji tek nastaju. `created_by`
je `Pravopis srpskoga jezika (Matica srpska)`.

Ključ (`[pravopis:futur-sazeti]`) stoji u **samom tekstu** pouke. Ponovni upis nađe
staru po ključu i prepravi je. Da se prepoznaje po tekstu, svaka ispravka formulacije
ostavila bi zastarelu pouku aktivnom pored nove — i obe bi išle u prompt, jedna
protiv druge.

Upis vraća `{"upisano", "izmenjeno", "netaknuto"}` i zapisuje
`content.house_style.loaded`.

### 3. Pravopis se ne seče — ni budžetom, ni granicom broja

Ovo je bila najveća zamka i našao sam je merenjem, ne pretpostavkom. Šest pravila
zauzima **1541 znak** od 4000 (ADR-0052, budžet prompta). Staje. Ali:

- `prompt_section` puni budžet **poukama agenta prvo**. Deset ličnih pouka po 500
  znakova izbacuje ceo pravopis iz prompta;
- `active_for` uzima **deset najnovijih** pouka firme. Pravopis je upisan jednom i
  zauvek, pa je najstariji u kućnom stilu — jedanaesto pravilo firme bi ga tiho pojelo.

Petlja se zatvara na najgoru stranu: agent koji ne vidi pravopis greši u svakoj
rečenici, dobija odbijanje zbog toga, odbijanje postaje njegova lična pouka, a ta
pouka istiskuje pravopis još dalje. Što više greši, to manje vidi pravilo.

Zato:

- u `active_for`, pravopisne pouke ulaze **van granice broja** (`PROMPT_LIMIT_GLOBAL`
  važi samo za ostali kućni stil);
- u `prompt_section`, red punjenja je **pravopis → pouke agenta → sektor → ostali
  kućni stil**. Pravopis nije mišljenje urednika nego način na koji jezik radi; lična
  pouka mu ne može biti preča.

### 4. `manage.py kucni_stil` — ručno, i gašenje uz razlog

```
manage.py kucni_stil --spisak
manage.py kucni_stil --upisi
manage.py kucni_stil --ugasi navodnici --zasto "klijent traži engleske navodnike"
```

`--actor` mora da počne sa `user:`. Ova pravila idu u **svaki** prompt za pisanje,
svakom agentu; takvu odluku ne donosi servis. Gašenje traži `--zasto` i zapisuje
`content.house_style.disabled` — ako neko za godinu pita zašto agenti pišu engleske
navodnike, odgovor stoji u zapisu.

## Šta je odbačeno

- **Ceo Pravopis u prompt.** 1.268.656 znakova; plaća se po pozivu i ne staje. Prompt
  nosi šest pravila koja se krše stalno; ostatak ide u bazu znanja, gde se pita po
  potrebi (sledeći korak: Rečnik uz Pravopis, 4.919 odrednica sa brojem tačke).
- **Pravila iz mog sećanja na srpski pravopis.** Pravopis je bio na disku. Pravilo
  bez broja tačke ne bi imalo čime da se potkrepi, a pravopisna pravila su upravo
  mesto gde „znam da je tako" najčešće nije tako.
- **Preslovljavanje izvornika na latinicu radi upisa.** Pravila o slovima i o pisanju
  glasova gube smisao preslovljena. Šest pravila su izabrana tako da važe u oba pisma,
  a primeri su latinični jer agenti tako pišu.
- **`learn()` za ova pravila.** `learn()` vezuje pouku za personu i akciju urednika;
  ova nastaju iz knjige i ne pripadaju nijednom nacrtu. Poseban ulaz je jasniji od
  `learn()` sa praznom personom.
- **Automatska ispravka teksta pred objavu** (lint nad nacrtom koji sam menja `znat ću`
  → `znaću`). Prvo treba da vidimo koliko model greši kad pravilo *ima* u promptu;
  popravljač koji krije grešku onemogućava merenje. Ako se pokaže da greši i dalje,
  to je svoj ADR.
- **`is_active=False` kao podrazumevano po upisu.** Pravilo koje je upisano pa ugašeno
  ne radi ništa, a izgleda kao da radi.

## Posledice

- `apps/content/pravopis.py` (novo), `lessons.upisi_kucni_stil`, `lessons.OZNAKA_PRAVOPIS`,
  izmenjeni `active_for` i `prompt_section`, `manage.py kucni_stil` (novo).
- Bez migracije — `EditorialLesson` već ima sve što treba.
- 15 novih provera; ukupno **1020**.
- Posle deploy-a treba jednom pokrenuti `manage.py kucni_stil --upisi`. Dok se ne
  pokrene, ništa se ne menja.

## Zapisano za ADR-0033

Prva verzija ovog ADR-a bila je gotova sa šest pravila i komandom, i tu sam hteo da
stanem. Pravopis bi ušao u prompt — i ispao iz njega prvi put kad agent zaradi deset
ličnih pouka, tiho, bez ijedne greške u zapisu.

Našao sam to tako što sam **izmerio koliko pravila zauzimaju i pročitao kojim redom
se budžet puni**, a ne tako što sam pretpostavio da „staje pa je u redu". Pravilo koje
iz toga sledi: **kad se nešto dodaje u prompt, proverava se i po kom redu prompt seče.**
Mesto u prompt-u nije isto što i mesto u bazi.
