# ADR-0018 — Lik agenta: profilna slika i galerija

- **Status:** prihvaćeno
- **Datum:** 23.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §1, §9.4 t.7, §13.2, §17 · Aneks A §2 · ADR-0013, ADR-0017
- **Kod:** `apps/visuals/generator.py`, `apps/visuals/storage.py`,
  `apps/visuals/management/commands/portrait.py`, `config/settings/base.py`,
  `policy/capabilities.yaml`, `console/`, `tests/test_visuals.py`

## Kontekst

Agent bez lica nije osoba. Potrebne su dve stvari: **profilna slika** za
stranicu i naloge, i **galerija** slika za objave. Tvrd zahtev je da to bude
**ista osoba na svakoj slici** — inače je to skup stranaca pod jednim imenom.

Provajder: **OpenAI, model `gpt-image-2`** (odluka Slobodana, 23.09.: „Možemo
da koristimo ChatGPT za slike"). Koristi se API, ne ručni rad u ChatGPT-u —
10.000 agenata se ne crta rukom. Cena je u trenutku odluke bila oko
0,005–0,21 $ po slici, zavisno od veličine i kvaliteta; na srednjem kvalitetu
profilna + pet slika po agentu je oko 0,25 $.

## Odluke

### 1. Portret je sidro identiteta

Postupak ima dva koraka:

1. **Portret** se pravi jednom, pozivom `/images/generations`, iz opisa izgleda
   u dosijeu (ADR-0017). Upisuje se kao `MediaAsset` vrste `FACE_REFERENCE` i
   postavlja na `VisualProfile.reference_asset`.
2. **Svaka sledeća slika** nastaje pozivom `/images/edits` **sa tim portretom
   kao ulazom**, uz uputstvo „ista osoba, nepromenjeno lice, druga scena". Tako
   galerija ostaje jedno lice.

Bez portreta nema galerije — `make_photo` odbija rad sa `NO_REFERENCE`.

### 2. Izvor izgleda je dosije, ne prompt iz koda

`appearance_of()` čita `PersonaDossier.appearance_prompt`; ako ga nema, sastavlja
opis od građe, kose i očiju; tek na kraju pada na stari `VisualProfile.style_prompt`.
Razlog: dosije je ono što operater menja u konzoli, pa je on izvor istine.
Radno mesto se dodaje u prompt, da portret odgovara poslu.

### 3. Šta se proverava, i gde

Proverava se **tekst koji je uneo čovek** (scena, opis izgleda) — ne naš
sopstveni šablon, u kom iste reči stoje kao zabrana („bez logotipa”). Provera
je pre poziva provajderu, pa se zabranjena slika nikada ne plaća:

- tvrde zabrane iz `guards.prohibitions` (`REAL_PERSON_LIKENESS` i ostale);
- spisak onoga što slika ne sme da prikaže: tuđi logotip ili brend, vodeni žig,
  lična dokumenta, kreditna kartica, policijska i vojna uniforma. Oblici su
  srpski, pa se traži koren reči, ne cela reč.

Uz to, sam prompt portreta izričito traži izmišljenu osobu koja ne liči ni na
jednu stvarnu.

### 4. Svaka slika nosi svoje poreklo

`origin=generated`, `generation_model`, `generation_prompt_hash` i `rights_note`
(„sintetička slika, ne prikazuje stvarnu osobu, objavljuje se uz AI oznaku").
Fajl ide u MinIO pod ključem `personas/<ID>/<hash>.png`, pa ista slika ne
zauzme dva mesta; u bazi su samo metapodaci. Ista slika za istu personu se ne
upisuje dvaput (provera po `sha256`).

### 5. Trošak i plafon

Svaka slika se knjiži u `CostLedger`, bucket `media_generation`, cena iz
`IMAGE_PRICE_MICRO_EUR` (ista jedinica kao kod LLM ruta, pa je zbir uporediv).
Plafon je `IMAGES_PER_DAY` po agentu (podrazumevano 20); preko toga
`THROTTLED`. Ključ provajdera prati pravilo iz ADR-0013: agent sme da ima svoj
(`OPENAI_API_KEY_P00001`), inače se koristi zajednički.

### 6. Zašto slika ne ide kroz Action i odobrenje

Generisanje slike nema spoljašnji efekat — ništa ne izlazi iz sistema, a poziv
pokreće čovek klikom u konzoli. Zato ide direktno, uz audit, plafon i trošak,
isto kao izrada nacrta teksta. **Objava** te slike je druga stvar: ona ide kroz
`Action`, policy i odobrenje, kao i svaki drugi sadržaj. Tip
`visual.generate` je upisan u `capabilities.yaml` bez sposobnosti, da bi
kasnije mogao da dobije pravilo kada agent bude sam tražio sliku.

### 7. Konzola

Kartica **Lik** na strani agenta: profilna, galerija, dugme „Napravi profilnu"
i polje za scenu. Slike se prikazuju preko `/console/assets/<IMG-…>` — samo
prijavljenom operateru, bez javnog linka ka storage-u. Komandna linija:
`manage.py portrait --persona P-00001 [--scene "…"] [--show]`.

## Posledice

- Nova zavisnost: `boto3` (S3 API za MinIO). MinIO je do sada stajao u
  compose-u a Django ga nije koristio — od sada koristi.
- Dok je `IMAGE_ENABLED=false`, ništa se ne generiše i ništa se ne plaća.
- 451 test (dodato 11 + 1 u konzoli).

## Šta ostaje

- **AI oznaka na samoj slici** tamo gde platforma to traži (Meta od 31.08.2026)
  — proveriti da li izlaz nosi C2PA zapis i, ako ne, dodati vidljivu oznaku
  pre prve objave.
- Izbor između kvaliteta `low`/`medium`/`high` posle prvih slika: razlika u
  ceni je desetostruka, pa se odlučuje gledanjem, ne pretpostavkom.

## Dopuna 24.09.2026. — ručno napravljene slike

Slobodan je odlučio da za **prvih stotinak agenata slike pravi ručno**, u
ChatGPT prozoru, umesto preko API-ja. (Ispravka broja koja je pratila odluku:
2.500 $ je procena za svih 10.000 agenata; za sto agenata je oko 25 $.)

Zato `IMAGE_ENABLED` ostaje `false`, a dodat je put za **otpremanje**:

- `generator.import_image(persona, data, as_portrait=…, label=…)` — upisuje
  sliku koju je napravio čovek. Ne zove nijedan provajder, **ne troši ništa** i
  ne dodiruje dnevni plafon.
- Tip fajla se čita iz sadržaja (PNG, JPEG, WebP), ne iz imena; najviše 12 MB;
  isti fajl se ne upisuje dvaput (`sha256`).
- Slika i dalje nosi sve što nosi i generisana: zapis u `MediaAsset`, oznaku da
  je sintetička (`rights_note`), audit. Umesto imena modela stoji `ručno`, pa
  se u svakom trenutku zna šta je nastalo kako.
- Otpremljena slika sa oznakom „kao profilna" postaje
  `VisualProfile.reference_asset` — isto sidro identiteta kao da je generisana,
  pa kasniji prelazak na API ne traži nikakvu prepravku.
- Konzola: forma za otpremanje u kartici **Lik** (uvek vidljiva); dugmad za
  generisanje se pokazuju samo kada je `IMAGE_ENABLED=true`.
- Komandna linija: `manage.py portrait --persona P-00001 --upload lik.png
  --kao-profilnu` i `--upload sajam.png --opis "na sajmu"`.

Za doslednost lika pri ručnom radu važi isto pravilo kao kod API-ja: **uz svaku
novu sliku priložiti profilnu** i tražiti istu osobu. Razlika je samo u tome ko
pritiska dugme.

459 testova (dodato 8).

**Ispravke posle prve upotrebe (24.09.):**

- otpremanje prima **više slika odjednom** (najviše 20); ako je čekirano
  „prva je profilna", prva postaje profilna, ostale idu u galeriju;
- profilna se prikazuje **umanjeno**: kao mali okrugli lik u zaglavlju strane
  agenta i kao sličica u kartici „Lik" — ne u punoj veličini. Veličina je
  zadata i atributom na `img`, ne samo u CSS-u, da keširan stil ne može da je
  poništi.
