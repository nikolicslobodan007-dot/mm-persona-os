# ADR-0103 — Nacrt postaje dokument

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Agentov posao se završavao kao `ContentItem.body` — tekst u bazi.
  Čoveku koji taj posao naručuje treba fajl koji može da otvori i pošalje.
- **Prethodi:** ADR-0018 (skladište), ADR-0024 (koraci sadržaja), ADR-0098
  (tuđi izvor pod licencom), ADR-0077 §3 (zakucan commit)
- **Menja:** `pyproject.toml`, `apps/visuals/storage.py`,
  `apps/content/dokument.py` (novo), `apps/content/steps.py`,
  `tests/test_dokument.py` (novo)
- **Canon:** §2.2 (`IMG-` public_id), §9.4

## Izmereno pre odluke

`HKUDS/CLI-Anything`, commit `34f51953`, **Apache-2.0**, 51.3k zvezdica.
Iz njega uzimamo jedan podpaket: `libreoffice/agent-harness`
(`cli-anything-libreoffice`, 704 KB, zavisnosti `click`, `prompt-toolkit`,
`defusedxml`).

Probano u pravom radu, ne pročitano iz opisa:

| Format | Kako nastaje | Traži LibreOffice |
|---|---|---|
| `odt`, `ods`, `odp`, `html`, `txt` | biblioteka piše XML sama | **ne** |
| `docx`, `pdf`, `xlsx`, `pptx`, `csv` | ODF pa `libreoffice --headless` | **da** |

**Moja greška u toku merenja, zapisana:** prvo sam zaključio da `docx` i `pdf`
rade bez LibreOffice-a, jer su fajlovi nastali sa praznim `PATH`-om. Netačno —
`find_libreoffice()` traži i izvan `PATH`-a, po uobičajenim putanjama, i našao
ga je. Zaključak sam izvukao pre nego što sam pročitao tu funkciju.

Druga zamka, izmerena: `export render izlaz.docx` **bez** `--preset docx` tiho
napravi ODT sa imenom `.docx`. Zato naš kod uvek prosleđuje preset izričito.

## Odluka

**1. Uzimamo tuđe, celo i nepromenjeno.** Zavisnost u `pyproject.toml`,
**zakucana na commit** — isti URL u drugom trenutku daje drugi sadržaj, isti
razlog kao `commit_sha` u ADR-0077 §3.

**2. Koristi se kao biblioteka, ne kao program.** Zovemo Python funkcije
(`create_document`, `add_heading`, `add_paragraph`, `export`). Nema
pokretanja ljuske, nema novog prava „agent sme da pokrene komandu". Taj
razgovor dolazi kad dođe; ovde nije potreban.

**3. Pravljenje dokumenta nema spoljašnji efekat, pa nema ni odobrenje.**
Fajl ostaje u našem skladištu. Ista granica kao kod `content.draft`
(ADR-0024): objava i slanje su odvojena vrata i ostaju zatvorena.

**4. Podrazumevan format je `odt`** — jedini koji sigurno radi u svakoj slici.
`docx` i `pdf` su dozvoljeni, ali kad LibreOffice nedostaje, greška **imenuje
uzrok i nabraja formate koji rade bez njega**. Tiho prazan fajl je gori od
greške koja zaustavi posao.

**5. Dokument je `MediaAsset` sa `kind=DOCUMENT`.** Ta vrednost je već
postojala u `AssetKind`; ništa se ne dodaje u zaštićeni `common/enums.py`.
Public_id ostaje `IMG-…` jer tako kaže Canon §2.2 za `MediaAsset` — vrstu
nosi `kind`, ne prefiks, i prefiks se ne menja usput.

**6. Isti nacrt u istom formatu daje isti ključ u skladištu**, pa drugi poziv
vraća postojeći red umesto da pravi duplikat. Ključ se računa iz **posla**
(`id` nacrta, format, `content_hash`), ne iz otiska bajtova.

Zašto baš tako — izmereno, ne pretpostavljeno: prvo sam ključ vezao za otisak
fajla i test `test_isti_nacrt_ne_pravi_drugi_red` je pao. **ODF je ZIP, a ZIP u
sebe upisuje vreme pravljenja**, pa isti nacrt dva puta daje različite bajtove
i time nov red pri svakom pozivu. Otisak bajtova ostaje upisan u `sha256`
reda — to jeste checksum tog fajla — ali identitet dokumenta nosi posao.
Provera postojećeg reda ide **pre** izvoza, pa se drugi put ne radi ni
posao.

**7. Novi korak plana `content.document`.** Uzima poslednji nacrt iz istog
plana i pravi fajl. Format se zadaje u koraku.

## Šta ovo NE radi

- **Dokument i sadržaj nisu povezani u modelu.** `ContentAsset` traži
  `AssetRole`, a tamo nema vrednosti za dokument; dodavanje vrednosti u
  `AssetRole` je izmena zaštićenog `common/enums.py` i zaslužuje svoju
  odluku, ne usputnu. Za sada veza postoji u izlazu koraka i u auditu
  (`sadrzaj` = id nacrta). Zapisano kao dug.
- **Oblikovanje je najprostije moguće:** naslov je naslov, prazan red deli
  pasuse. Nema stilova, tabela, zaglavlja ni logotipa. Kad zatreba, biblioteka
  sve to ume — mi još nemamo šta da stavimo u njih.
- **`docx` i `pdf` neće raditi dok LibreOffice ne uđe u sliku.** To je
  posebna odluka o veličini slike i donosi se kad bude potrebna.
