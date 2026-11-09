# ADR-0130 — Dnevni autopilot sakuplja sam i uvozi SLOBODNA bez čoveka u petlji

- **Status:** prihvaćen (09.11.2026.)
- **Povod:** Slobodan: „Neka vuče svakog dana po 10 kom. I da onda znamo na čemu
  smo. Trebalo bi ih malo uposliti, jer ne možemo sve da radimo nas dvojica."
  Cilj: sakupljanje veština da teče samo, bez ljudskog pokretanja svaki dan.
- **Prethodi:** ADR-0127 (sakupljač: ingest + destilacija), ADR-0059 (sme da
  sakuplja, ne sme da prisvoji — kutije licence), ADR-0074 (uvoz veštine pokreće
  čovek, `--actor user:`), ADR-0032 (izviđanje — agent prati nove alate)
- **Menja:** `apps/memory/management/commands/signali.py` (novo, GitHub Signals
  izvor), `apps/memory/sakupljanje/ulaz.py` (github repo → pun README),
  `apps/memory/tasks.py` (`memory.github_signals_dnevno`), `config/celery.py`
  (beat). **Ne menja** `common/enums.py` ni modele.
- **Canon:** §10.4, §10.5, §11.1 (beat)

## Šta se desilo

GitHub Signals (`githubsignals.io`) je kurirani feed novih open-source projekata
sa gotovim mašinskim ulazima (CSV izvoz, RSS). To je idealan izvor za sakupljač
(ADR-0127) i za izviđanje-agenta (ADR-0032). Slobodan je tražio da se sakupljanje
pretvori u dnevni autopilot — agenti rade, ne on.

ADR-0127 je već predvideo ovaj korak u „Sledeće": _„Opc. `--uvezi` da `sakupi` sam
pozove uvoz (kad se licenca reši automatski/interaktivno)."_ Ovaj ADR ga donosi.

Prepreka je ADR-0074: **uvoz veštine pokreće čovek** (`--actor user:`), jer
materijal za bazu znanja daje čovek. Autopilot koji ništa ne uvozi nije autopilot
— sabrano bi večno čekalo ručni korak. Pitanje je gde tačno povući granicu.

## Izmereno pre odluke (09.11.)

| pitanje | izmereno |
|---|---|
| čita li se repoova licenca pouzdano | **da** — GitHub API `license.spdx_id` je repoova SOPSTVENA deklaracija (iz LICENSE fajla), ne naše nagađanje |
| koje kutije postoje | `LicenseBox`: SLOBODNA, ZARAZNA, ZABRANJENA, NEPOZNATA (ADR-0059 §2) |
| šta sme u klijentski projekat | `LICENSE_BOXES_USABLE = {SLOBODNA}` — samo SLOBODNA; sistem to već ograничava nizvodno |
| da li destilat prepisuje izvor | **ne** — destilovana veština je NAŠ opis postupka (ADR-0059 §3, ADR-0074 t.3), ne tekst izvora |
| traži li `uvezi()` `user:` prefiks | **ne** — prefiks proverava samo komanda `vestina`; `uvezi()` prima `actor` i radi pod `bind()` |
| ponaša li se „top N" bez beleženja | **zaglavi se** — bira se po zvezdicama među repoima kojih nema u bazi; nezabeleženi non-SLOBODNA ostaju na vrhu i troše destilaciju svaki dan |

## Odluka

### 1. GitHub Signals je nov izvor sakupljača

Komanda `signali`: `--lista` (nabraja iz `/export.csv`), `--sakupi` (batch
destilacija, dedup protiv baze), `--licence` (SPDX → kutija + `vestina` komande),
`--auto` (sakupi + auto-uvoz). Github repo se čita kao **pun README** (`raw`), ne
HTML landing (ADR-0127 ingest, prošireno). Video na feed-u (Telegram/YouTube) je
sekundaran; repo je vrednost.

### 2. Dnevni autopilot (Celery beat)

`memory.github_signals_dnevno` (beat `github-signals-dnevno`, crontab 05:17 UTC,
queue `maintenance`) jednom dnevno sakupi 10 novih repoa i pozove auto-uvoz.
Beat je kanonski mehanizam periodike (§11.1), ne spoljni cron.

### 3. Relaksacija ADR-0074: SLOBODNA se auto-uvozi, ostalo čeka čoveka

Ovo je jezgro odluke. ADR-0074 je rekao: uvoz pokreće čovek. Ovaj ADR ga **sužava**,
ne ukida:

- **SLOBODNA** (MIT/Apache/BSD/ISC…) → **auto-uvoz kao upotrebljivo**, pod
  `actor=user:slobodan`.
- **NEPOZNATA/ZARAZNA/ZABRANJENA** → **zabeleženo sa pravom kutijom, ali
  NEupotrebljivo** (sistem pušta samo SLOBODNA). Čeka Slobodanov pregled /
  reklasifikaciju pre nego postane upotrebljivo.

`actor=user:slobodan` nije impersonacija: Slobodan je 09.11. doneo **stajaću
odluku** da se SLOBODNA auto-uvozi. Autopilot izvršava njegovu odluku, pa audit
pošteno pokazuje čiju. (Razlikovanje od ručnog uvoza: naslov izvora „GitHub
Signals: <repo>".)

### 4. Zašto je ovo bezbedno (a ADR-0074 i dalje drži za ono što je bitno)

- Granica koju ADR-0074 štiti — da se **tuđe ne prisvoji** — ostaje netaknuta:
  upotrebljivo je i dalje samo SLOBODNA (repoova sopstvena dozvola), i to je naš
  opis, ne prepis (ADR-0059 §3).
- Odluku o kutiji ne donosi agent napamet — чита se repoova deklaracija (SPDX).
  Gde deklaracije nema → NEPOZNATA → neupotrebljivo. Nepoznato nije „slobodno".
- Beleženje non-SLOBODNA je nužno za napredak i protiv dvostrukog plaćanja; ono
  ih ne čini upotrebljivim.

## Posledice

- Sakupljanje veština teče samo, dnevno. Čovek pregleda samo non-SLOBODNA.
- „Da znamo na čemu smo": `vestina --spisak --izvor "GitHub Signals"` + beat log.
- Dedup je protiv baze (uvezeni izvori), pa rebuild i re-run ne plaćaju ponovo.

## Sledeće

- Reklasifikacija non-SLOBODNA: tok da čovek pregleda zabeležene NEPOZNATA i
  podigne kutiju kad utvrdi licencu.
- Bogatiji dnevni izveštaj (event/dokument umesto loga).
- `GITHUB_TOKEN` u prod env za veći dnevni obim provere licenci (limit 60→5000/h).
