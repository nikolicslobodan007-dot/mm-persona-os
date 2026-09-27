# ADR-0052 — Zaglavlje hunka se prebrojava, ne odbija

- **Status:** prihvaćen (27.09.2026.)
- **Prethodi:** ADR-0049 (aritmetika hunkova), ADR-0038 (zakrpa), ADR-0050, ADR-0051
- **Menja:** ADR-0049 — stavku „Ispravljanje pogrešnog `@@` u naše ime" u *Šta je odbačeno*

## Šta se desilo

Sa ispravljenim promptom (ADR-0051) Lazar je prestao da ponavlja zakrpu i počeo da
piše nove. Tri puta zaredom je promašio isto:

```
27.09 12:10  prijavljeno -6 +20 | izbrojano -6 +18
27.09 14:44  prijavljeno -6 +20 | izbrojano -6 +18
27.09 15:19  prijavljeno -6 +19 | izbrojano -6 +18
```

Pomerio se za jedan. To nije brojanje nego pogađanje, i neće se popraviti još
jednim objašnjenjem: brojanje redova u sopstvenom izlazu je poznata slaba tačka
ovakvih modela. Do tada je potrošeno 41 od 60 centi, a u kod nije ušlo ništa.

Naš lanac je pri tom radio tačno kako je ADR-0049 zamislio — hvatao je grešku u
aplikaciji, sa preciznom porukom, pre poslušnika. Radio je i nije vredelo.

## Odluka

### 1. Brojevi u `@@` se računaju iz tela hunka

`zakrpa.prebroj_hunkove(diff) → (zakrpa, ispravke)`. Telo hunka je samodovoljno:
završava se na sledećem `@@`, na sledećem fajlu ili na kraju — a `_nov_fajl` i
`diff --git` su granice koje već umemo da čitamo. Za dato telo postoji **tačno
jedan** ispravan par brojeva.

Zato ovo nije nagađanje. ADR-0049 je odbio ispravljanje zaglavlja uz obrazloženje
„zakrpa bi se primenila, a kod bi bio drugi od recenziranog". To obrazloženje važi
za nagađanje **sadržaja**; prebrojavanje ne dira nijedan red koda. Pomešao sam dve
stvari kad sam pisao ADR-0049.

### 2. Šta se ne dira

- **Početni brojevi reda** (`-6`, `+22`). Oni nose nameru — gde izmena ide — i nisu
  izvedivi iz tela. Računati njih bilo bi pogađanje, i ostaje odbijeno.
- **Oznaka odeljka** iza drugog `@@` (`@@ … @@ def prompt_section(self):`) —
  prenosi se netaknuta.
- **Zakrpa bez ijednog `@@`** — preimenovanje i izmena moda prolaze kao i do sad.

### 3. Šta ostaje greška

Red u telu koji ne počinje razmakom, `+`, `-` ni `\`. Takav red se ne može ni
prebrojati, pa se ne može ni ispraviti; i dalje je `BAD_HUNK`.

### 4. Ispravka nije tiha

Ovo je jedini deo odluke koji nosi stvaran rizik, pa se protiv njega gradi:

> Ako je pisac **hteo** duži hunk pa ga je odsekao, zaglavlje je jedini trag te
> namere. Prebrojavanje bi tu nameru ćutke izbrisalo i prihvatilo osakaćenu
> verziju.

Zato ispravka ide:

- u `reason` zakrpe — `zaglavlja hunkova prebrojana (ADR-0052): red 4: -1 +9 → -1 +1
  — proveri da hunk nije odsečen`;
- u `task.patch.submitted` zapis, kao `details.ispravke`;
- odatle u brif sledećeg pokušaja (ADR-0050 §2), pa pisac zna šta smo mu uradili;
- i pred recenzenta-čoveka, koji sudi da li je hunk odsečen.

Tiha ispravka bila bi gora od odbijanja. Zapisana nije.

### 5. Čuva se ispravljena zakrpa

`submit` upisuje diff sa prebrojanim zaglavljima, jer je to ona koja će se
primeniti — zapis mora da odgovara onome što se izvršava. Original nije izgubljen:
`reason` kaže šta je pisalo pre.

## Šta je odbačeno

- **Ostati pri odbijanju (ADR-0049).** Tri plaćena poziva i tri ista promašaja su
  mera te odluke. Provera koja tačno imenuje grešku koju druga strana ne ume da
  otkloni nije kapija nego naplatna rampa.
- **Tiha ispravka.** Vidi §4.
- **Računanje početnih brojeva reda.** To jeste nagađanje namere; ADR-0049 je tu u
  pravu i ta stavka ostaje.
- **Popravljanje kroz `git apply --recount`.** Radi isti posao, ali traži `git` i
  radni primerak, kojih u aplikaciji nema (ADR-0041 §1). Aritmetika ih ne traži.
- **Uputstvo modelu da pažljivije broji.** Probano tri puta, u sve jačem obliku,
  uključujući nalaz sa tačnim brojevima. Uputstvo koje mora da se ispoštuje da bi
  valjan rad prošao nije provera nego zamka (ADR-0048).

## Posledice

- `zakrpa.Ispravka`, `prebroj_hunkove`, prošireni `Nalaz` (`ispravke`, `diff`),
  izmenjeni `check` i `submit`; `_HUNK` sada hvata i rep zaglavlja.
- 19 provera prepisano ili dodato u `tests/test_zakrpa.py`, jedna u
  `tests/test_brif.py`. Ukupno 989.
- Nema migracije. Zatečene zakrpe se ne diraju.

## Zapisano za ADR-0033

Ovo je peti put u tri dana da se ista greška pojavi u meri agentovog rada, samo
što je ovog puta greška bila **moja odluka**, ne moj propust: ADR-0049 je odbio
prebrojavanje na osnovu obrazloženja koje se odnosi na nešto drugo. Rečenicu
„zakrpa bi se primenila, a kod bi bio drugi od recenziranog" napisao sam ne
proveravajući da li važi za slučaj koji sam njome odbijao. Ne važi.

Pravilo koje iz toga sledi: **obrazloženje odluke se proverava nad slučajem koji ta
odluka odbija**, ne nad onim koji joj je bio na pameti.
