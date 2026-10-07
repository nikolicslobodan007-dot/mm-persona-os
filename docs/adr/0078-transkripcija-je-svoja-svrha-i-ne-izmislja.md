# ADR-0078 — Transkripcija je svoja svrha, i kad ne može, ćuti

- **Status:** prihvaćen (07.10.2026.)
- **Prethodi:** ADR-0074 (dvoja vrata; transkripcija je treći korak redosleda),
  ADR-0076 (strana `Izvori`), ADR-0077 (korpus na prva vrata), ADR-0009
  (lanac ruta, lokalni šablon poslednji), ADR-0033 (pravilo nula)
- **Menja:** `common/enums.py` (**zaštićena zona — piše čovek**),
  `apps/llm_gateway/gateway.py`, migracija za `LLMRoute.purpose` ako polje nosi
  `choices`
- **Canon:** §10.4, §10.5

## Šta se desilo

Slobodanov stvarni postupak je: vidi snimak na telefonu, snimi ekran, i hoće da
ono što je na snimku **rečeno** postane znanje njegovih agenata. Bez pretvaranja
zvuka u tekst, strana `Izvori` prima link i stoji — red čekanja se puni, a ništa
iz njega ne izlazi.

ADR-0074 je transkripciju stavio kao **treći korak** redosleda: komanda →
strana → transkripcija. Prva dva rade od 04. i 06.10. Ovo je treći.

## Izmereno pre pisanja (07.10.)

| pitanje | izmereno |
|---|---|
| koje svrhe ruta postoje | `planning`, `content_draft`, `reply`, `summarise`, `classify`, `embed`, `evaluate`, `code_patch` — **transkripcije nema** |
| ima li `AssetKind` zvuk | **ima** — `AUDIO`, uz `AVATAR`, `FACE_REFERENCE`, `PHOTO`, `VIDEO`, `DOCUMENT`, `THUMBNAIL` |
| šta `MediaAsset` nosi | `public_id`, `persona`, `kind`, `storage_key`, `mime_type`, `sha256`, `width`, `height`, **`duration_ms`**, `origin`, `generation_model`, `generation_prompt_hash`, `rights_note` |
| ima li `MediaAsset` polje za tekst | **nema** |
| koje svrhe smeju nad osetljivim | `SENSITIVE_ALLOWED_PURPOSES` = **samo `summarise`** |
| kako se zove ulaz u gateway | `generate` — tekst unutra, tekst napolje; uz `local_route`, `routes`, `persona_env_name`, `credential_ref` |
| veličine | `gateway.py` 13.396 B, `apps/policy/gateway.py` 7.229 B, `common/enums.py` **42.641 B** |
| rute u bazi | šest redova, tri svrhe; lokalni šablon prioritet 1000, anthropic 10; `reply` kod anthropica isključen |

## Odluka

### 1. Transkripcija je nova svrha rute, i dodaje je čovek

`LLMPurpose` dobija novu vrednost. To je izmena u `common/enums.py`, a taj fajl
je **zaštićena zona** — nijedan agent, nijedan nivo. Prvi korak ovog posla
piše čovek, isto kao popravka audita iz ADR-0076 §4.

Ako `LLMRoute.purpose` nosi `choices`, izmena traži migraciju; kapija
`migrations` će to javiti i to je ispravno ponašanje, ne kvar.

Razlog zašto svrha mora da postoji, a ne da se transkripcija zakači na
`summarise`: svrha je ono po čemu se bira ruta, meri trošak i proverava sme li
se poslati. Svrha koja laže o tome šta radi razbija sva tri.

### 2. Zvuk ne dobija nov model

`MediaAsset` sa `kind=AUDIO` već nosi sve što treba: gde fajl stoji
(`storage_key`), šta je (`mime_type`), koliko traje (`duration_ms`), otisak
(`sha256`) i pravo korišćenja (`rights_note`). Nov model bi bio druga tabela za
isti podatak.

### 3. Zvuk ne ide kroz `generate`

`generate` je napravljen za tekst unutra i tekst napolje. Zvuk je drugi oblik
poziva — fajl, trajanje, format. Dobija **svoju ulaznu tačku** u istom modulu,
sa istim lancem ruta, istim merenjem troška i istim `PromptRecord`/`LLMUsage`
zapisom. `generate` se ne dira.

### 4. Kad transkripcije nema, sistem ćuti — ne izmišlja

ADR-0009 kaže: lokalni šablon je uvek poslednji u lancu. Za tekst to je
razumno — šablon da nešto slabije ali istinito.

**Za zvuk nije.** Lokalni šablon ne može da čuje; sve što bi vratio bio bi
izmišljen prepis. Zato je poslednji član lanca za ovu svrhu **odbijanje sa
razlogom**, ne lažan izlaz. Dok ne postoji uključena ruta sa provajderom koji
ume da sluša, transkripcija **ne radi i to kaže naglas**.

Ovo je jedini izuzetak od ADR-0009 i važi isključivo za ovu svrhu.

### 5. Snimak izlazi iz kuće — provajder se bira merenjem

Transkripcija znači da Slobodanov zvuk odlazi tuđem serveru. Pravilo kuće stoji
iznad udobnosti: **provajder koji sme da uči na našim podacima se odbija za
svaku svrhu.** `LLMRoute` to već nosi kao `data_training_allowed`; red se ne
pravi dok se za tog provajdera ne izmeri, iz njegovih uslova, da na nama ne uči.

Dok takav red ne postoji, tačka 4 važi: ćutanje, ne izmišljanje.

### 6. Osetljiv materijal za sada ne ide na transkripciju

`SENSITIVE_ALLOWED_PURPOSES` danas sadrži **samo** `summarise`. Nova svrha se
**ne dodaje** u taj skup ovim ADR-om. Ako se ikada doda, to je zasebna odluka sa
zasebnim merenjem, i opet u zaštićenoj zoni.

### 7. Prepis nije znanje

Transkript je **sirovina**, ne veština. ADR-0074 §3 stoji: u bazu znanja ide
naš opis postupka, adresa i kutija licence — nikad doslovan prepis izvora.
Transkript zato **ne ulazi u `KnowledgeFact.object_json`**, ni u celosti ni u
delovima.

Gde transkript stoji nije odlučeno ovde, jer nije izmereno: `MediaAsset` nema
polje za tekst, a da li `ContentAsset` odgovara — **nije provereno**. Prvi
zadatak koji ovo sprovodi **počinje tim merenjem**, i mesto se bira tek onda.
Pretpostavka o mestu je upravo ono što pravilo nula zabranjuje.

## Šta je odbačeno

- **Da transkripcija koristi `summarise` rutu.** Svrha koja laže o poslu razbija
  izbor rute, merenje troška i proveru dozvola.
- **Lokalni šablon kao poslednji član lanca.** Za zvuk bi to bio izmišljen
  prepis, a izmišljen prepis je gori od nikakvog.
- **Nov model za zvuk.** `MediaAsset` sa `AUDIO` već postoji.
- **Proširenje `generate` da prima i fajlove.** Dva oblika poziva u jednoj
  funkciji znači da svaka buduća izmena dira i tekstualni put.
- **Da agent napiše izmenu `common/enums.py`.** Zaštićena zona, i ostaje
  zaštićena.
- **Da se transkript upiše kao veština.** ADR-0074 §3.

## Posledice

- Posao ima **dva dela**: čovek dodaje svrhu u `common/enums.py` (plus migracija
  ako je traži), agent piše ulaznu tačku u `apps/llm_gateway/gateway.py`.
  To su dva zadatka, ne jedan, i prvi nema izvršioca-agenta.
- Red u `LLMRoute` se upisuje komandom `llm_route`, kad provajder bude izmeren.
- `common/enums.py` je 42.641 B — daleko iznad praga od 12.000 B (ADR-0075), pa
  bi agent i da sme dobio samo izvod. Još jedan razlog zašto taj deo piše čovek.
- Posle transkripcije, red čekanja sa strane `Izvori` konačno ima izlaz: izvor
  bez datoteke može da postane izvor sa znanjem.

## Zapisano za ADR-0033

Krenuo sam da pišem ovaj ADR sa pretpostavkom da zvuk treba nov model i da
transkripcija ide kroz `generate`. Oba su pala na merenju: `AssetKind` već ima
`AUDIO`, a `generate` je napravljen za tekst. Merenje je trajalo dve komande i
uštedelo ceo jedan pogrešan zadatak.

Druga stvar koju bih bez merenja propustio: `SENSITIVE_ALLOWED_PURPOSES` je
**samo** `summarise`. Da nisam pogledao, nova svrha bi ćutke nasledila
pravila za koja niko nije odlučio da važe.
