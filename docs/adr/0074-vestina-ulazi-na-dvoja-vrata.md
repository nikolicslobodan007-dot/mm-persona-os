# ADR-0074 — Veština ulazi na dvoja vrata, i nijedna ne prepisuje tuđe

- **Status:** prihvaćen (04.10.2026.)
- **Prethodi:** ADR-0059 (sakupljanje znanja i licenca), ADR-0055 (rečnik kao
  uvoz), ADR-0032 (izviđanje), ADR-0031 (sloj znanja), ADR-0033 (pravilo nula)
- **Menja:** `apps/memory/vestine.py` (novo), `manage.py vestina` (nova komanda),
  `tests/test_vestine.py` (novo). **Ne menja** `common/enums.py` ni modele.
- **Canon:** §10.4, §10.5

## Šta se desilo

Slobodan je 04.10. opisao postupak koji radi rukom:

> „Ja na svom FB nalogu vidim neki video koji mi je interesantan. Onda snimim
> ekran i pošaljem ga da mi se analizira. Meni je potreban neko ko će sve to da
> radi umesto mene."

Cilj koji je izrekao: **puniti bazu veština koju AI agenti koriste.**

ADR-0059 je 03.10. postavio pravilo i bravu — licencu, `knowledge.collect`,
CHECK u bazi. Ovaj ADR postavlja **put**: odakle veština ulazi i u kom obliku
ostaje.

## Izmereno pre pisanja (04.10.)

Nijedna odluka ispod nije doneta iz sećanja.

| pitanje | izmereno |
|---|---|
| ima li model za veštinu | `KnowledgeFact` ima `subject`, `predicate`, **`object_json`**, `confidence` (CHECK 0–1), `provenance`, `valid_from/to`, vezu na `KnowledgeSource` |
| ima li presedan za uvoz | **da** — `apps/content/recnik.py`: `get_or_create` po naslovu, ponovni uvoz briše i upisuje u jednoj transakciji, sve u audit |
| koje vrste izvora postoje | `SourceKind` ima pet: `SYSTEM_OBSERVATION`, `FIRST_PARTY_USER_INPUT`, `PUBLIC_WEB_SOURCE`, `LLM_INFERENCE`, `SYNTHETIC_WORLD_EVENT`. **Nema „video" ni „kanal".** |
| ima li kanal sa pokazivačem | **ne** — `KnowledgeSource` je jedan dokument, nema ni roditelja ni pokazivača dokle se stiglo |
| ima li komanda za unos | **ne** — u `apps/memory/management/commands` stoje samo `memory_eval` i `memory_seal` |
| ima li transkripcija | **ne** — nijedan deo sistema ne pretvara zvuk ni sliku u tekst |

## Odluka

### 1. Veština je `KnowledgeFact`, ne nov model

| polje | šta nosi |
|---|---|
| `subject` | ime veštine, onako kako bi je agent tražio |
| `predicate` | **`vestina.postupak`** |
| `object_json` | koraci, ulazi, uslovi, zamke — **našim rečima** |
| `source` | `KnowledgeSource` sa `uri` i kutijom licence |
| `confidence` | koliko verujemo da postupak radi kako je opisan |

Presedan je `pravopis.odrednica` (ADR-0055) i radi u pogonu od 28.09. Nov model
bi značio drugu tabelu, druge migracije i drugo mesto za istu grešku — a nijedno
pitanje na koje `KnowledgeFact` ne odgovara nije izmereno.

Prefiks `vestina.` nije ukras: po njemu se ponovni uvoz zna šta briše, isto kao
`recnik.uvezi()` nad svojim predikatom.

### 2. Dvoja vrata, i razlikuju se po tome **ko je doneo materijal**

Ovo je jezgro odluke. Do sada smo o sakupljanju govorili kao o jednoj stvari.
Nije jedna.

| | **predato** | **sakupljeno** |
|---|---|---|
| ko donosi materijal | čovek — pošalje link ili snimak | agent — sam ode i uzme |
| `source_kind` | `FIRST_PARTY_USER_INPUT` | `PUBLIC_WEB_SOURCE` |
| ko pokreće | čovek, komandom | raspored ili zadatak |
| dozvola agenta | **nijedna** — agent ništa spolja ne radi | `knowledge.collect` **i** `web.read_public` (ADR-0059) |
| spoljni efekat | nema ga | ima — `robots.txt`, `Crawl-delay`, uslovni GET, `CONTROLLED_LIVE` |
| kad se pravi | **prvo** | tek kad prvo prođe |

Pravopis je ušao kroz prva vrata, komandom koju je pustio čovek, i zato nije
tražio nijednu dozvolu ni GO odluku. Veština koju Slobodan pošalje ulazi
**istim vratima**.

Posledica koja se lako previdi: **prva vrata rade danas.** Ne čekaju ni Meta
recenziju, ni ključ, ni `CONTROLLED_LIVE`, ni GO odluku. Jedino što im fali je
transkripcija, kad je materijal snimak a ne tekst.

### 3. Prepis nije znanje

Ovo je Slobodanovo pravilo prevedeno u oblik koji se može proveriti:

> „Nećemo da krademo, hoćemo da sakupljamo. Nikada neću da nečiju knjigu
> objavim kao svoju."

Zato:

- **Ostaje:** naš opis postupka, adresa izvora, kutija licence, ime autora kad
  je poznato.
- **Ne ostaje:** doslovan prepis tuđeg videa, teksta ili snimka. Prepis je
  **radni materijal** — živi dok traje vađenje veštine i briše se sa njim.

Brava je strukturna, ne disciplinska: `object_json` nema polje za sirov prepis,
pa ga nema gde ni upisati. Provera koja to čuva pada ako se takvo polje ikad
pojavi.

Ovo je isto pravilo kao ADR-0059 §3 — **ponašanje se sme preuzeti, izraz ne** —
samo spušteno na jedan red u bazi.

### 4. Licenca se ne pretpostavlja

Podrazumevana kutija je `NEPOZNATA` i znači **nema dozvole**, ne „slobodno je"
(ADR-0059 §2). Snimak na društvenoj mreži je gotovo uvek `NEPOZNATA`. To ne
zabranjuje da se iz njega nauči postupak — zabranjuje da se njegov **izraz**
negde pojavi kao naš.

`LICENSE_BOXES_USABLE` i dalje sadrži samo `SLOBODNA`.

### 5. Transkripcija ide kroz gateway, kao svaki drugi spoljni poziv

Nije poseban slučaj i ne dobija zaobilaznicu:

- ruta se podešava komandom, kao sve ostale (ADR-0009);
- **provajder koji sme da uči na našim podacima se odbija** — postojeće pravilo,
  polje `data_training_allowed`;
- ključ ide po agentu, u fajl, u bazi samo referenca (ADR-0026).

Lokalni model na serveru se **ne razmatra**: CX23 ima 2 vCPU i 4 GB, a na njemu
već stoji devet kontejnera. To je mera, ne mišljenje.

### 6. Slavina je strana u konzoli, ne komanda

Komanda je vodovod. Čovek koji šalje materijal treba **slavinu**, i ona mora da
radi sa telefona — jer se snimak i vidi na telefonu.

| gde | radi sa telefona | šta traži |
|---|---|---|
| **konzola, nova strana `Izvori`** | **da** — čovek je već prijavljen | malu stranu, po uzoru na `Grane` (ADR-0071) |
| komandna linija | ne | ništa — radi odmah, ali ne na telefonu |
| mejl agentu | verovatno | **neizmereno** — ne zna se da li dolazna pošta igde sleće |

Odluka: **konzola.** Jedno polje za adresu, jedno za datoteku, jedno za kutiju
licence. Konzola već prima datoteku i to ima svoj test
(`tests/test_console.py::test_upload_from_console`), pa se ne pravi nov put nego
se dodaje strana.

Mejl se ne odbacuje nego **ostaje neizmeren**, i tako se i zapisuje. Dok se ne
izmeri gde dolazna pošta sleće, o njemu nema odluke.

Redosled je obavezan i nije stvar ukusa: komanda prva, jer strana bez nje nema
šta da zove.

### 7. Kanal sa pokazivačem se **ne pravi sada**

Spisak praćenih kanala sa pokazivačem dokle se stiglo je tačna potreba — ali
**druga vrata**, ne prva. Dok čovek donosi materijal, kanal nema šta da pamti.

Uslov koji ga pokreće, zapisan da se ne pomera: **prvi adapter koji sam ode po
materijal.** Tada, i ne pre toga.

Razlog za ovu uzdržanost je u istoriji ovog istog spisa: ADR-0059 je stajao
napisan i nepokrenut **pet nedelja**, a u sebi je nosio pouku da je ADR-0032
ležao pet dana. Model koji niko ne pokreće nije temelj nego dug.

## Šta je odbačeno

- **Čitanje Slobodanovog feeda.** Traži prijavu kao on. To nije samo kršenje
  uslova platforme nego lažno predstavljanje, i ne radi se ni sa odobrenjem.
- **Nov model `Skill`.** Druga tabela za ono što `KnowledgeFact` već nosi.
- **Čuvanje prepisa kao znanja.** Udobno i korisno — i to je tačno ono protiv
  čega smo postavili ADR-0059.
- **YouTube kao prvi izvor.** Tehnički najlakši put (ključ je besplatan, titlovi
  dolaze gotovi), ali **Slobodan nema YouTube nalog**, a ima Fejsbuk stranice.
  Lakši put kojim niko ne ide nije lakši.
- **Čekanje Meta app review-a da bi se počelo.** Review traži nedelje, a prva
  vrata ne zavise od njega.

## Posledice

- `apps/memory/vestine.py` — `uvezi(izvor, vestine)`, po uzoru na
  `content/recnik.py`: idempotentno po naslovu izvora, brisanje i upis u jednoj
  transakciji, `audit.record("memory.vestina.loaded", …)`.
- `manage.py vestina --izvor <naslov> --uri <adresa> --licenca <kutija> --datoteka <json>`
  — komandu pušta **čovek**; `--actor` mora da počne sa `user:`.
- `tests/test_vestine.py` — idempotentnost, kutija licence se ne pretpostavlja,
  `object_json` nema polje za prepis, ponovni uvoz ne ostavlja stare redove.
- `console` — strana `Izvori`: adresa, datoteka, kutija licence. **Posle**
  komande, nikad pre nje.
- `SourceKind`, `LicenseBox` i modeli **ostaju nepromenjeni**.

Troje se radi **jedno po jedno, i svako se izmeri pre sledećeg**: komanda →
strana → transkripcija. Nijedno od to troje ne čeka Meta recenziju; ona ide
paralelno, jer traje nedeljama i ništa je ne ubrzava.

## Zapisano za ADR-0033

Tri puta sam u ovom poslu krenuo da pravim ono čega nema, a nisam pogledao šta
postoji. Rečnik je 28.09. rešio uvoz znanja celim postupkom — idempotentnost,
transakciju, audit — i taj postupak je stajao u `apps/content/recnik.py` dok sam
ja juče objašnjavao kako nam fali put za unos.

Pouka nije „pogledaj kod pre nego što pišeš ADR". Pouka je uža: **kad nešto već
jednom uđe u bazu kako treba, taj put je presedan, a ne anegdota.**
