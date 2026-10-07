# ADR-0076 — Izvori ulaze sa telefona, a datoteka je neobavezna

- **Status:** prihvaćen (06.10.2026.)
- **Izvršilac:** Pavol Hudák P-00029 — isti koji je pisao stranu `Grane` (ADR-0071)
- **Prethodi:** ADR-0074 (dvoja vrata, §6 slavina), ADR-0059 (licenca se ne
  pretpostavlja), ADR-0071 (strana `Grane`), ADR-0055 (rečnik kao uzor uvoza),
  ADR-0033 (pravilo nula)
- **Menja:** `console/views.py`, `console/urls.py`,
  `console/templates/console/izvori.html` (novo), `tests/test_console.py`
- **Canon:** §10.4, §10.5

## Šta se desilo

Komanda `vestina` radi od 04.10. i radi dobro. Ali radi **samo iz terminala**,
a Slobodanov stvarni postupak izgleda ovako:

> „Ja na svom FB nalogu vidim neki video koji mi je interesantan. Onda snimim
> ekran (pošto gotovo uvek to radim preko telefona)…"

Čovek koji materijal vidi na telefonu ne može da pusti komandu koja traži
pripremljen JSON na disku. ADR-0074 §6 je to već zaključio i odlučio da slavina
bude **strana u konzoli**. Ovaj ADR je sprovodi — i usput ispravlja dve stvari
koje je §6 rekao prekratko.

## Izmereno pre pisanja (06.10.)

Nijedna odluka ispod nije doneta iz sećanja.

| pitanje | izmereno |
|---|---|
| sme li Pavol na `console` | **da** — `code.write@L1` nad `console`, uz `apps/channels`, `apps/content` i `deploy.stage` svuda |
| koliki je `console/views.py` | **43.242 B** — ulazi u opseg ceo, pa opseg mora da ostane uzak |
| ima li uzor za stranu | **da** — `console/templates/console/branches.html`, 2.408 B, Pavolov rad |
| prima li konzola već datoteku | **da** — `tests/test_console.py::test_upload_from_console` |
| sme li izvor da postoji bez unesenog znanja | **da** — `ingested_at` je `null=True`, `retrieved_at` je `null=True` |
| traži li baza adresu uvek | **ne** — `knowledge_source_web_has_uri` traži adresu **samo** za `public_web_source`; naš `first_party_user_input` je ne traži |
| šta traži `SLOBODNA` | `knowledge_source_free_names_license`: ako je kutija `SLOBODNA`, `license_note` ne sme biti prazan |
| koliko polja komanda zaista traži | **pet**: `--izvor`, `--uri`, `--licenca`, `--naziv-licence` (kad je SLOBODNA), `--datoteka` |

## Odluka

### 1. Strana `Izvori` zavodi izvor; datoteka je neobavezna

ADR-0074 §6 je nabrojao **tri** polja — adresu, datoteku, kutiju licence. To je
bilo prekratko: komanda traži **pet**, jer bez naslova izvora nema po čemu da
bude idempotentan, a bez naziva licence baza odbija `SLOBODNA` (izmereno
04.10., na mom zapisu). Strana nosi svih pet, a datoteka je **jedina
neobavezna**.

| poslato | šta se desi |
|---|---|
| izvor **i** datoteka | veštine se uvoze odmah, istim putem kao komanda |
| izvor **bez** datoteke | izvor se zavede i stoji — znanja još nema |

Razlog je Slobodanov stvarni tok: na telefonu ima **link**, nema JSON. Strana
koja traži datoteku je tačna po slovu §6 a beskorisna u ruci.

### 2. Zaveden izvor nije unesen izvor, i to se vidi u bazi

Izvor bez datoteke dobija `retrieved_at` (kad je čovek poslao) i **`ingested_at`
ostaje prazan**. To nije nov model i nije nova tabela — oba polja su već
`null=True` i upravo za ovo i postoje.

Spisak izvora koji čekaju je time **upit, ne nov red u šemi**:
`ingested_at IS NULL`. Kad transkripcija proradi, ona puni te izvore i upisuje
`ingested_at`. Dotle je to Slobodanov red čekanja, i vidi se.

**Dopunjeno 07.10. posle prvog otvaranja strane.** Slobodan je otvorio stranu i
u redu čekanja zatekao **dva izvora koja su odavno uvezena** — rečnik sa 8.797
činjenica i Pravilo nula sa jednom. Izmereno odmah zatim:

| provera | rezultat |
|---|---|
| izvora u bazi | 2 |
| sa praznim `ingested_at` | **2** |
| gde se `ingested_at` uopšte pominje u kodu | migracija, model, i nova strana — **i nigde više** |

**Nijedan uvoz nikada ne upisuje to polje.** Ni `apps/memory/vestine.py`, ni
`apps/content/recnik.py`. Polje stoji u šemi od prve migracije i nikad nije
postavljeno, pa `ingested_at IS NULL` u pogonu ne znači „čeka" nego „uvek".

Odluka ostaje — **upit je ispravan, podatak nije.** Oba uvoza dobijaju obavezu
da pri upisu činjenica postave `ingested_at`. Dva postojeća izvora se popravljaju
jednokratno, rukom, jer **jesu** uvezeni.

Pouka za ADR-0033 je oštra i vredi je zapisati tačno: **gradio sam uslov na
polju koje niko ne puni, i to nisam izmerio.** Proverio sam da polje *sme* da
bude prazno (`null=True`) i stao tu — a pravo pitanje nije sme li biti prazno
nego **da li ga iko ikada popuni**. Kvar nije uhvatilo ni moje čitanje zakrpe ni
četiri zelene kapije; uhvatilo ga je to što je čovek otvorio stranu i pogledao
šta na njoj piše.

### 3. Pravila su ista kao u komandi, i proveravaju se u strani

- `licenca` je spisak od četiri kutije, podrazumevana je `NEPOZNATA`;
- `SLOBODNA` **bez naziva licence se odbija u strani**, sa porukom čoveku, a ne
  u bazi sa `IntegrityError` (ADR-0059 §2; kvar koji sam napravio 04.10.);
- `source_kind` je uvek `FIRST_PARTY_USER_INPUT` — materijal donosi čovek.

Strana ne sme da bude blaža od komande. Dvoja vrata do iste baze koja ne traže
isto su rupa, ne udobnost.

### 4. Pokretač se zapisuje onako kako mehanizam dozvoljava

**Ispravljeno 07.10. posle merenja.** Prvi oblik ove tačke tražio je da audit
nosi prijavljenog čoveka kao pokretača. To je **zahtev koji sistem ne
dozvoljava**, i to je moja greška iste vrste kao ona od 04.10.

Izmereno je potpis funkcije:

```
audit.record(event_key, *, severity, persona, action, run, before, after, details)
```

**Parametra `actor` nema.** Nijedan pozivalac ga ne može proslediti — ni ova
strana, ni komanda `vestina`, ni `recnik`. Zato strana radi ono što je jedino
moguće: upisuje prijavljenog čoveka u `details`, u obliku `user:korisnicko_ime`,
isto kao postojeći pozivaoci.

Prava rupa je time **imenovana i locirana**: nije u pozivaocima nego u
`api/audit.py`. Taj fajl je **zaštićena zona** — nijedan agent ga ne sme dirati
ni na kom nivou poverenja, pa ispravku mora da napiše čovek, zasebnim ADR-om.
Dok se to ne desi, Canon §8.5 ostaje neispunjen i to stoji zapisano ovde, a ne
sakriveno u jednom zadatku.

### 5. Strana ne dira ništa spolja

Link se **zavodi, ne preuzima**. Nema zahteva ka Fejsbuku, nema `robots.txt`,
nema `CONTROLLED_LIVE`. To su druga vrata (ADR-0074 §2) i ona čekaju GO odluku.
Strana ostaje unutar prvih vrata, gde dozvola ni ne treba.

## Šta je odbačeno

- **Da strana sama ode po link.** To je spoljni efekat i druga vrata.
  `GLOBAL_EXTERNAL_ACTIONS_ENABLED=false` stoji.
- **Da datoteka bude obavezna**, kako §6 doslovno kaže. Tada strana sa telefona
  ne radi, a telefon je ceo razlog zašto je pravimo.
- **Nov model „red čekanja".** `ingested_at IS NULL` je isti podatak bez druge
  tabele i bez druge migracije.
- **Da strana sama zove transkripciju.** Transkripcije još nema. Strana koja
  zove ono čega nema je pretpostavka ugrađena u kod.
- **Da se `console/views.py` deli na manje fajlove usput.** Možda i treba, ali
  to je zaseban posao sa zasebnim merenjem; vezivati ga za ovaj znači dve
  izmene u jednoj zakrpi.

## Posledice

- `console/urls.py` — nova putanja `izvori`.
- `console/views.py` — pregled zavedenih izvora i obrada poslatog obrasca;
  uvoz ide kroz **postojeći** `apps.memory.vestine.uvezi`, ne kroz nov put.
- `console/templates/console/izvori.html` — mala strana po uzoru na
  `branches.html`.
- `tests/test_console.py` — piše ih **drugi agent** (`RAZ-TES`), ne Pavol:
  izvor bez datoteke ostaje sa praznim `ingested_at`; `SLOBODNA` bez naziva
  licence pada u strani a ne u bazi; neprijavljen čovek ne vidi stranu.
- **Rebuild je obavezan** — `console` je u slici aplikacije. Posle spajanja ide
  `up -d --build`. (Izuzetak važi samo za izmene pod `tests/`.)
- Redosled iz ADR-0074 ostaje: komanda → strana → transkripcija. Ovo je drugi
  korak, i ne preskače treći.

## Zapisano za ADR-0033

ADR-0074 sam napisao sa „Menja: `apps/memory/vestine.py`" a da nisam proverio
sme li iko tamo — svi programeri su bili `L0` i zadatak bi bio odbijen. Ovaj
ADR je napisan tek **pošto** je izmereno da Pavol ima `code.write@L1` nad
`console`.

Druga pouka je iz istog dana, 06.10., i tiče se reda poslova: **ispravka
sopstvenog rada traži se posle spajanja, ne pre.** Agent svaki put dobija
fajlove iz glavne grane; dok njegov raniji rad tamo ne stigne, svaka „sitna
ispravka" znači pisanje svega iznova — a svako pisanje iznova nešto izgubi.
Danas je tako nestao jedan koristan `assert`, a ispravka jednog komentara
koštala je 26 od 35 centi.
