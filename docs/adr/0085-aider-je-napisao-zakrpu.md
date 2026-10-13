# ADR-0085 — Aider je napisao zakrpu; šav se otvara, zapis je ono što fali

- **Status:** prihvaćen (13.10.2026.)
- **Povod:** ADR-0081 je tražio tri merenja pre nego što se napiše jedan red
  šava. 13.10. su puštena — na pravom zadatku, ne na probi.
- **Prethodi:** ADR-0081 (pisac sme da bude tuđi), ADR-0082 (aider u kavezu),
  ADR-0084 (veština stiže do agenta), ADR-0050 (zakrpa modela), ADR-0033
  (pravilo nula)
- **Menja:** `apps/orchestration/brif.py` i `tests/test_brif.py` — zakrpu nije
  napisao naš `pisac` nego Aider. Šav u kodu se ovim ADR-om **ne** piše; piše se
  posle tačke „Šta ostaje da se izmeri".
- **Canon:** §7.3, §10.4

## Postavka merenja

Aider 0.86.2 pušten **rukom**, u `web` kontejneru, nad privremenim klonom `main`-a
(`9dac051`), sa brifom zadatka `TSK-01M4RRBFPXM9XSCJE904HVTWB0` („Brif nosi
veštine iz dozvoljenih kutija licence", izvršilac P-00028). Brif je napravljen
našim `pisac._prompt()` — isti tekst koji bi dobio i naš pisac, **115.856 B**.

Nijedan red koda nije menjan da bi merenje prošlo.

## Tri prepreke, sve naše

Sve tri su bile na našoj strani, i svaka je izmerena pre nego što je dirana:

| # | šta je stalo | zašto | kako je rešeno |
|---|---|---|---|
| 1 | `sh: 1: git: not found` | ADR-0082 je uneo Aidera u sliku, a `git` u slici ne postoji | `--no-git` — Aider menja fajlove, razliku računa `git` na hostu |
| 2 | `Missing Anthropic API Key` | ključ nije u `.env.prod` nego kao fajl `0600` u `/secrets`, po personi (ADR-0026) | ključ se čita iz `/secrets/anthropic_P-00028.key` u promenljivu okruženja, nigde se ne ispisuje |
| 3 | `temperature is deprecated for this model` | Aider svakom zahtevu dodaje `temperature`; `claude-sonnet-5` je više ne prima | `use_temperature: false` u fajlu podešavanja modela |

Prva je moja greška i stoji pod imenom: u `Dockerfile` sam uneo alat, a nisam
izmerio da u slici postoji jedino što tom alatu treba spolja. ADR-0033.

## Izmereno

Jedan pokušaj, bez ijedne ispravke posle:

| | naš `pisac` (12.10.) | Aider (13.10.) |
|---|---|---|
| pokušaja | 3 | **1** |
| ishod | 3 × REJECTED | zakrpa u oba fajla |
| razlog odbijanja | 1 × „nije vratio diff", 2 × hunk se završava izmenjenim redom | — |
| tokeni po pokušaju | ~29k poslato | **114k poslato, 27k primljeno** |
| cena po pokušaju | 10–13 c | **$0,50** |
| ukupno | 35 c, nula koda | $0,50, 111 redova |

Zakrpa: **6.459 B, 2 fajla, 111 dodatih redova.**

Kapije nad svežim klonom `main`-a sa primenjenom zakrpom, isti postupak koji
vrti poslušnik (`deploy/runner/docker-compose.zadatak.yml`):

**pytest ZELENO · ruff ZELENO · canon_lint ZELENO · migrations ZELENO · ishod 0**

**1236 prošlo, 1 preskočen** (220,06 s). Brojka se slaže red po red: 1232 osnova
+ 4 nova testa iz ove zakrpe.

## Ono što smo pogrešno predvideli

ADR-0081 je ceo argument za Aidera gradio na **mapi repozitorijuma** — da ona
zamenjuje naš `_izvod` koji baca imena na nivou modula. Danas je mapa bila
**isključena**: `--no-git` je gasi (`Repo-map: disabled`), jer se mapa pravi iz
`git` istorije koje u slici nema.

Dakle pobeda nije došla odatle odakle smo je čekali. Došla je od **oblika
izmene**: `whole edit format` — model vraća ceo fajl, Aider sam računa razliku.
Nema hunka, pa nema ni porodice kvarova koja je 12.10. odbila dva od tri
pokušaja. To je i razlog zašto je poslato 114k umesto 29k tokena: ceo fajl ulazi
i ceo izlazi. Četiri puta skuplje po pokušaju, i uspešnost 1/1 prema 0/3.

Iz ovoga sledi da ADR-0080 (`MIN_IZVOD_PROCENAT`) **nije mrtav teret**, kako je
ADR-0081 pretpostavio. Ostaje na snazi dok se ne izmeri šav sa upaljenom mapom.

## Kvalitet zakrpe, pročitan a ne pretpostavljen

Zakrpa je pročitana red po red i upoređena sa `common/enums.py` i
`apps/memory/models.py` pre nego što su kapije puštene:

- `_vestine()` filtrira tačno po ADR-0084 — predikat `vestina.postupak`,
  `source__is_active=True`, `source__license_box__in=LICENSE_BOXES_USABLE`;
- uz svaku veštinu idu `source_title` i `license_note` — znanje bez porekla ne
  izlazi iz baze;
- veštine ulaze u **isti plafon** kao referenca i priručnik; šta ne stane ide u
  `truncated` sa razlogom, ne nestaje tiho;
- četiri nova testa poštuju `CHECK knowledge_source_free_names_license` (kutija
  `SLOBODNA` mora da imenuje licencu).

U komentaru koji je model sam napisao stoji i ovo: biranje koja veština ide kom
agentu se **namerno ne radi**, populacija je jedan, pravilo izbora se piše tek
posle merenja (ADR-0077). To nije prepisano iz brifa — to je razumevanje brifa.

## Odluka

1. Zakrpa ulazi u `main`. Pisac je imenovan u poruci commita: napisao ju je
   Aider 0.86.2 modelom `anthropic/claude-sonnet-5`, po brifu ovog zadatka.
2. Šav iz ADR-0081 se otvara — unutar `pisac.pokusaj()`, i nigde drugde. Iznad i
   ispod šava se ne menja ništa: zadatak, persona, poverenje po putanji,
   `zakrpa --proveri`, četiri kapije, grana.
3. Aiderov poziv u šavu ide sa `--no-git` i `use_temperature: false`, dok se ne
   izmeri suprotno. `git` u sliku ulazi tek kad za njega postoji izmeren razlog.

## Šta ostaje da se izmeri pre nego što se šav napiše

Od tri stavke iz ADR-0081 dve su danas zatvorene — **gde se vrti** (`web`
kontejner, privremeni primerak, bez dodira sa `/app`) i **trošak po pokušaju**
($0,50). Treća stoji otvorena i ona je ceo preostali posao:

**Zapis.** Aider zove model sam, pa `PromptRecord` i `LLMUsage` o tom pozivu ne
znaju ništa. Danas cena postoji samo kao red na ekranu. Šav mora da uhvati, po
pokušaju: model, otisak brifa, poslate i primljene tokene, cenu.

Uz to ide jedno pitanje koje se **ne sme izmisliti**: Aider cenu prijavljuje u
dolarima, a naš zapis vodi µEUR (`LLMUsage`, ADR-0062). Kurs je odluka, ne
zaokruživanje — ulazi u zaseban ADR sa izmerenim izvorom kursa.

Dok zapis ne radi, Aider se pušta **rukom i uz nadzor**, kao danas. Automatski
ne.
