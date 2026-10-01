# ADR-0065 — Hunk mora da ima rep, i ispis mora da kaže čija je zakrpa merena

- **Status:** prihvaćen (01.10.2026.)
- **Prethodi:** ADR-0048 (zakrpa bez `git` zaglavlja), ADR-0049 (neprimenjena
  zakrpa), ADR-0052 (zaglavlje hunka se prebrojava), ADR-0060 (priručnik),
  ADR-0033 (pravilo nula)
- **Menja:** priručnik `RAZ-PRO`, pravilo 2 — „minimalni unified diff je
  dovoljan" je bilo **netačno**
- **Canon:** §6.4 (izvršni ugovor)

## Šta se desilo

01.10. je `TSK-01M3V1NV6S82R25AMH8E6JWYNK` bio prvi zadatak pisan sa
priručnikom. Tri zakrpe, 18 centi, sve tri primljene kao `ACCEPTED` — i nijedna
nije stigla do kapija. Poslušnik je svaku odbio sa:

```
error: patch failed: tests/test_lessons.py:189
error: tests/test_lessons.py: patch does not apply
```

Zakrpa je bila ispravna po **svemu što proveravamo**: putanje u dozvoljenim
granicama, aritmetika hunkova tačna (ADR-0052 je čak ispravio `-189,9` u
`-189,7`, i to ispravno), a kontekst koji je model napisao postoji u fajlu bajt
po bajt, na redu 202. Otisci fajla u slici i u repozitorijumu identični.

Falio je **jedan red konteksta iza poslednje izmene**. Izmereno nad pravim
`git`-om, nad pravim fajlom, istom sadržinom i istom pozicijom:

| završnog konteksta | `git apply --check` |
|---|---|
| 0 redova | **odbija** — `patch does not apply` |
| 1 red | prolazi |
| 2 reda | prolazi |

Hunk koji dopire do **kraja fajla** je izuzetak: tamo repa nema odakle i `git`
ga ne traži.

## Odluka

### 1. Zakrpa bez repa se odbija pri predaji, ne kod poslušnika

`zakrpa.proveri_rep` ulazi u `check`, dakle u isti put kojim prolazi svaka
zakrpa. Poruka kaže šta tačno fali i gde:

> `tests/test_lessons.py`: hunk u redu 3 se završava izmenjenim redom.
> `git apply` takav hunk odbija — dodaj bar 1 red konteksta iza poslednje izmene
> (red 209 fajla), i uračunaj ga u brojeve u `@@` zaglavlju.

Provera gleda **stvarni fajl** iz istog stabla iz kog brif čita (`BASE_DIR`),
jer se izuzetak na kraju fajla iz zaglavlja ne vidi. Fajl koji se ne može
pročitati se **preskače**: ovo je pomoć piscu, ne drugi sloj dozvola, a tiho
odbijena ispravna zakrpa je gora od propuštene (ADR-0053).

Provera se vrti nad **ispravljenom** zakrpom (ADR-0052), jer se ona i primenjuje.

### 2. Priručnik je lagao, i to je ispravljeno

Pravilo 2 je glasilo: „Minimalni unified diff je dovoljan: `---`, `+++`, `@@`."
To nije tačno — dovoljan je za **naš parser**, ne za `git apply`. Agent je radio
tačno po pravilu koje smo mu dali i tri puta pao zbog njega.

Novo pravilo 2 nosi oba uslova i izvor `ADR-0048, ADR-0065`.

### 3. Ispis zadatka kaže čija je zakrpa merena

`zadatak --zadatak TSK-…` prikazuje kapije poslednje **izmerene** zakrpe. Kad
posle nje stigne novija koja do kapija nije došla, ispis je do danas ćutao — pa
sam ja tri sata čitao ishod druge zakrpe kao ishod treće i tri puta ti rekao
pogrešnu stvar.

Sada ispis nosi red o poslednjoj zakrpi i upozorenje:

```
  zadnja zakrpa (01.10. 08:54): nije se primenila — apply --check: error: …
  PAŽNJA: kapije ispod su od ranije zakrpe, ne od ove.
```

## Šta je odbačeno

- **Sami dopisati red konteksta u agentovu zakrpu.** Primamljivo: fajl imamo, red
  znamo. Ali to je naše pisanje koda u njegovo ime, i prvi put kad pogodimo
  pogrešan red dobijamo zakrpu koja se primeni **na pogrešno mesto** i prođe
  kapije. ADR-0052 ispravlja **brojanje**, što je aritmetika; ovo bi bio sadržaj.
- **Pustiti poslušnika da to otkrije.** On to već radi i uredno prijavljuje
  (ADR-0049). Ali tada je pokušaj potrošen, a agent u brifu dobija poruku o
  `git`-u umesto rečenice o tome šta da promeni.
- **Proveriti pokretanjem `git apply --check` u aplikaciji.** Aplikacija nema
  radno stablo sa `.git` i ne sme da dobije Docker (ADR-0038 §2). Provera koja
  traži alat koji aplikacija ne sme da ima nije provera nego želja.
- **Dodati pravilo 15 umesto izmene pravila 2.** Dva pravila o istoj stvari se
  razilaze; netačno pravilo se ispravlja, ne dopunjuje.

## Posledice

- `apps/orchestration/zakrpa.py` → `proveri_rep`, `NAJMANJE_REPA`, poziv u `check`.
- `apps/personas/prirucnici.py` → pravilo 2 prepisano.
- `apps/orchestration/management/commands/zadatak.py` → red o poslednjoj zakrpi.
- `tests/test_zakrpa.py` → 5 novih provera; `tests/test_api_zadaci.py` → fikstur
  `DIFF`/`LOSA` dobio rep, jer je i on bio zakrpa koja se ne primenjuje.
- Ukupno **1147** provera.
- `TSK-01M3V1NV6S82R25AMH8E6JWYNK` — tri pokušaja odbijena zbog ovoga pripadaju
  `SISTEM`-u (ADR-0053), ne agentu.

## Zapisano za ADR-0033

**Prva:** napisali smo mu pravilo koje je bilo **netačno**, i ono je radilo
tačno kako piše. „Minimalni unified diff je dovoljan" bila je istina o našem
parseru, a ja sam je zapisao kao istinu o svetu. **Pravilo u priručniku se
proverava nad alatom koji ga izvršava, ne nad onim koji ga čita.**

**Druga:** danas sam četiri puta izneo uzrok pre nego što sam ga izmerio —
mešani `diff --git`, razlika između slike i repozitorijuma, kontekst bez vodećeg
razmaka, Unicode. Sve četiri sam proverio pre nego što bi ušle u ADR, i sve
četiri su pale. To je ispravan ishod **tog** pravila, ali tri od njih sam usput
izgovorio Slobodanu kao nalaz. **Hipoteza izgovorena naglas se pamti kao nalaz,
pa se izgovara tek kad prođe proveru.**

**Treća:** rekao sam da se neuspeh `apply`-a „nigde ne upisuje nego ostaje u
dnevniku". Nije tačno — ADR-0049 ga upisuje kao `REJECTED` sa razlogom. Pogrešio
sam jer ispis koji sam gledao prikazuje kapije, a ne zakrpe. **Kad mera izgleda
pogrešno, prvo se pita da li gledam pravi ispis** — i §3 postoji zato što taj
ispis zaista jeste ćutao o onome što je najvažnije.

**Četvrta:** agent je tri puta uradio posao ispravno i tri puta bio odbijen zbog
nas. Mera to sada zna (ADR-0053), ali vredi zapisati i zašto se to ponavlja:
**svaki put kad mu nešto uskratimo ili pogrešno kažemo, trošak snosi on, a ime
na odbijenici je njegovo.**
