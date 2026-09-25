# ADR-0036 — Mašinska recenzija kao prva kapija

- **Status:** prihvaćen (25.09.2026.)
- **Prethodi:** ADR-0035 (model zadatka), ADR-0034 (departman za programiranje),
  ADR-0033 (pravilo nula), ADR-0032 (izviđanje — presuda „uzimamo")
- **Canon:** §16.5 (audit), §21 (uslovi i licence)

## Šta je alat, provereno a ne pretpostavljeno

`alibaba/open-code-review`, **Apache-2.0** — licenca koja nas ne ujeda. Go binar sa
npm omotačem, `ocr` u putanji. Ume `text`, `json` i **`sarif`** izlaz. Proverena
verzija: `v1.12.9`, građena 22.09.2026.

Njegov rečnik, pročitan iz koda a ne iz README-a:

- **osam kategorija** (`ruleId`): `bug`, `security`, `performance`, `maintainability`,
  `test`, `style`, `documentation`, `other`;
- **četiri težine** koje se svode na tri SARIF nivoa: `critical`/`high` → `error`,
  `medium` → `warning`, `low` i sve nepoznato → `note`;
- **otisak po nalazu** (`partialFingerprints["ocrFinding/v1"]`), stabilan po
  putanji, kategoriji i zatečenom kodu.

## Odluka

### 1. Ulaz je SARIF, ne njihov JSON

SARIF 2.1.0 je OASIS standard. Vezujući se za njega, isti uvoznik sutra prima nalaze
iz `semgrep`-a, `codeql`-a ili bilo čega što ume SARIF — a `open-code-review` postaje
zamenljiv deo, ne temelj. Njihov sopstveni JSON bi nas vezao za jedan projekat.

Uvoznik je **strog**: ono što nije SARIF se odbija sa greškom. Prazan izveštaj je
uredan ishod i nije greška — tiho uvezenih nula nalaza nema.

### 2. Mašina ne postavlja `BLOCKER`

Preslikavanje: `error` → `MAJOR`, `warning` → `MINOR`, `note` i prazno → `NIT`.

Ovo je namerno jedan stepen niže nego što alat tvrdi. Razlog: model greši, a
`BLOCKER` zaustavlja zadatak. Kad bi mašina smela da blokira, ekipa bi naučila da
preskače blokade — i `BLOCKER` bi prestao da znači išta. Podizanje u `BLOCKER` je
zaseban, izričit potez recenzenta ili čoveka.

Izvorna težina se ne gubi: upisuje se u tekst nalaza, pa se uvek vidi šta je alat
zapravo rekao. Nalazi kategorije `security` sa nivoom `error` se posebno prebrojavaju
i ističu — jeftini su za proveru, skupi za promašiti.

Ovo je i razlog za naziv: mašinska recenzija je **prva kapija**, ne presuda.
Kapiju `review` i dalje zatvara recenzent komandom, uvoz je ne dira.

### 3. Nalaz van zadatka se ne kači na zadatak

Nalaz na fajlu koji nije pod dozvoljenim putanjama zadatka **ne postaje** nalaz tog
zadatka — zadatak ne odgovara za kod koji ne sme da dira (ADR-0035 §2). Takvi se
prebroje, upišu u audit i ispišu, pa čovek odluči da li iz njih nastaje nov zadatak.
Isto važi za nalaz u zaštićenoj zoni, samo glasnije.

### 4. Ponovljen uvoz ne pravi duplikate

`ReviewFinding` dobija `fingerprint` i jedinstvenost po paru (zadatak, otisak).
Recenzija se pokreće više puta nad istim zadatkom; bez ovoga bi svaki krug množio
iste nalaze i merenje iz ADR-0034 §6 ne bi značilo ništa.

### 5. Alat se ne pokreće iz Django procesa

Ovaj korak samo **uvozi** izveštaj. Pokretanje `ocr`-a traži radni primerak
repozitorijuma i ključ modela, a agent koji ima ljusku nad repozitorijumom je zasebna
odluka sa sopstvenim posledicama. Dok toga nema, komanda uvozi fajl.

## Šta je odbačeno

- **Njihov `--format json`.** Vezalo bi nas za jedan alat.
- **Da mašina zatvara kapiju `review`.** Prva kapija nije presuda.
- **Tiho preskakanje nalaza van putanja.** Podatak se ne baca zato što ne staje u
  kalup; prebroji se i prijavi.
- **Kačenje `fixes` iz SARIF-a kao predloženih zakrpa.** Predlog izmene koda koji niko
  nije pročitao je zamka; kad bude imalo ko da ga pročita, vraćamo se na to.

## Posledice

- `apps/orchestration/recenzija.py` + `manage.py recenzija --zadatak … --sarif …`.
- `ReviewFinding.fingerprint` i migracija.
- `ocr` se instalira gde se recenzija vrti (`npm i -g @alibaba-group/open-code-review`),
  a ne u sliku aplikacije — Django ga ne poziva.
- Sledeće, odvojeno: ko i kako pokreće `ocr` (agent sa radnim primerkom repozitorijuma),
  i promocija nalaza u `BLOCKER` kroz recenzenta.
