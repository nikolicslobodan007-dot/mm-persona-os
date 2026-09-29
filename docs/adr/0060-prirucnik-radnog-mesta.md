# ADR-0060 — Priručnik visi o radnom mestu, ne o agentu

- **Status:** predložen (29.09.2026.)
- **Prethodi:** ADR-0054 (kućni stil iz Pravopisa), ADR-0055 i ADR-0056 (znanje van
  prompta), ADR-0017 (radno mesto nije dozvola), ADR-0037, ADR-0022 (delegiranje),
  ADR-0059 (sakupljanje znanja i licenca), ADR-0006 (F4 memorija i znanje)
- **Menja:** ADR-0054 — pouke urednika više nisu jedini tekst koji ulazi u prompt
- **Canon:** §10 (memorija i poreklo), §17 (radna mesta), §6.4 (izvršni ugovor)

## Šta se desilo

29.09. uveče, Slobodan: **„Imamo mali milion skilova za UI/UX. TO TREBA DA UBACIMO u
AI Agente koji se bave time."**

Istog dana je izmereno stanje ekipe:

| | |
|---|---|
| agenata | 33 |
| ima rutinu | 33 |
| ima bar jednu dozvolu | 9 |
| ima svoj ključ | 2 |
| ima i ključ i dozvolu | **1** |

Ali ispod tih brojeva stoji nešto što se ne vidi u tabeli: **nijedan agent nema tekst
koji mu kaže kako se njegov posao radi.** Lazar piše upotrebljiv kod zato što model
zna da piše kod, ne zato što mu je Web Korporacija išta rekla o tome kako se ovde
piše. Réka bi trebalo da izviđa, a niko joj nije napisao šta izviđanje jeste.

ADR-0054 je uveo pouke urednika i dao dva sloja: **pravila firme** (važe svima) i
**lične pouke** (važe jednom agentu). Između ta dva fali treći, i to baš onaj koji je
Slobodan tražio: **kako se radi ovaj posao.**

To nije osobina agenta. To je opis posla.

## Odluka

### 1. Priručnik visi o radnom mestu

Ne o personi. `RAZ-PRO` ima priručnik za pisanje koda, `IST-ANA` za izviđanje,
`RAZ-BIB` za licence i biblioteku. Ko god sedne na tu stolicu, dobije ga prvog dana;
ko pređe na drugo mesto, dobije drugi, bez prepisivanja i bez „obuke".

Ovo je ista logika kao ADR-0017: **radno mesto nije dozvola** — ali jeste opis posla.
Dozvola kaže šta agent sme, priručnik kaže kako se to radi kad sme.

I to je jedini oblik koji izdržava cilj: **ne obučava se deset hiljada agenata nego se
napiše dvadeset priručnika.**

### 2. Dva sloja, po već izmerenom obrascu

Ceo priručnik ne ide u prompt. Budžet je 4000 znakova (`PROMPT_BUDGET_CHARS`), a
priručnik za UI/UX je višestruko veći od toga. Podela je ista kao juče kod Pravopisa,
i nije pretpostavka nego merenje:

| | u promptu | van prompta |
|---|---|---|
| pravopis (ADR-0054, 0055) | 6 pravila, **1541 znak** | **8.797** odrednica u bazi znanja |
| priručnik radnog mesta | **jezgro**, najviše 10–15 pravila | ceo tekst, čita se kad zatreba |

**Jezgro** je ono bez čega agent greši u svakom zadatku. Ostatak se ne pamti nego se
konsultuje — kao što `recnik.proveri` radi nad gotovim tekstom, a ne u promptu.

Ako jezgro ne stane, ne raste budžet nego se seče jezgro. Prompt koji je pun uputstava
nema mesta za zadatak.

### 3. Pravilo bez izvora ne ulazi ni ovde

Isto kao ADR-0054: svako pravilo u jezgru nosi odakle je. Iz priručnika — koja glava.
Iz nalaza — koji zadatak. Iz ADR-a — koji broj. **Pravilo koje niko ne može da
potkrepi je tvrdnja, ne pravilo**, i posle godinu dana se ne razlikuje od izmišljotine.

### 4. Tuđi priručnik se ne prepisuje

Postoje gotovi skupovi uputstava za UI/UX, pisani za druge sisteme. Oni idu kroz isti
filter kao svaki drugi tuđi tekst (ADR-0059 §2): licenca u četiri kutije, i **„nema
licence" znači „nema dozvole"**. Gde licenca ne dozvoljava, piše se svoj priručnik po
ADR-0059 §3 — iz opisa posla, ne iz tuđeg teksta.

Uz to, tuđi priručnik je pisan za tuđu mašinu. Naš agent ne piše fajlove nego predaje
zakrpu (ADR-0038), ne objavljuje nego predlaže (ADR-0043), i radi pod kapijama koje
tuđi priručnik ne poznaje. Prepisan tekst bi mu govorio o poslu koji ovde ne postoji.

### 5. Priručnik piše čovek, predlaže šef sektora

Prvi krug pišem ja i Slobodan odobrava — jer priručnik napisan iz pretpostavke je
najgori mogući oblik pretpostavke: ona koju svaki agent nasledi (ADR-0033).

Kasnije šef sektora predlaže izmenu iz nalaza; **odobrava čovek.** Agent koji sam sebi
piše opis posla nije opisan nego samozvan.

### 6. Priručnik koji ne menja ishod nije priručnik

Merilo je tvrdo i postavlja se **pre** pisanja: isti tri zadatka, izmereno pre i posle.

| | pre | posle |
|---|---|---|
| prihvaćenih zakrpa iz prvog pokušaja | ? | ? |
| prosečan broj pokušaja | ? | ? |
| cena po zadatku (centi) | ? | ? |
| kapija pala zbog stila, ne zbog logike | ? | ? |

Ako se brojevi ne pomere, priručnik se **gasi**, ne doteruje. Tekst koji ništa ne menja
i dalje jede budžet prompta koji nekom drugom treba.

## Šta je odbačeno

- **Sve u prompt.** Dvadeset strana uputstava izbacilo bi pouke urednika, pa i sam
  zadatak. Juče smo merili baš tu granicu (ADR-0054, budžet pouka) i znamo koliko je
  uska.
- **Priručnik po agentu.** Deset hiljada agenata bi značilo deset hiljada priručnika za
  posao koji je isti. Uz to bi svaki bio zasebno zastareo.
- **Kopiranje tuđih foldera sa uputstvima.** Licenca (ADR-0059) i pogrešna mašina.
- **Automatska izmena priručnika iz nalaza.** Nalaz je jedan slučaj; priručnik je
  pravilo. Put od jednog do drugog ide kroz čoveka, kao i `BLOCKER` (ADR-0036 §2).
- **Priručnik bez merila.** Odbijeno prvo, jer je najprivlačnije: tekst izgleda kao rad
  i niko ne pita da li radi.

## Posledice

- Nov nosilac priručnika — zaseban model ili `KnowledgeFact` sa opsegom radnog mesta.
  **Odlučuje merenje**, kad se vidi koliko polja zaista treba; ne bira se unapred.
- `brif.build` dobija odeljak „priručnik", sa svojim delom budžeta. Podela između pouka
  i priručnika je broj koji tek treba izmeriti — do tada priručnik ne sme da gura pouke.
- Prva tri priručnika, po tome gde već ima posla: **`RAZ-PRO`** (kako se ovde piše
  zakrpa), **`IST-ANA`** (kako se izviđa, ADR-0059), **`RAZ-BIB`** (licence i
  biblioteka).
- `manage.py prirucnik --mesto RAZ-PRO --spisak | --upisi | --ugasi <kljuc> --zasto "…"`,
  po uzoru na `kucni_stil`.
- Merenje iz §6 se upisuje **pre** prvog priručnika, nad zatečena tri zadatka.

## Zapisano za ADR-0033

**Prva:** Slobodan je ovo video pre mene, i video je iz prakse — imao je gotove
priručnike pred sobom i pitao zašto ih agenti nemaju. Ja sam tri dana gledao zašto
merenje laže, a nisam pitao **da li agent uopšte zna kako se posao radi.** Popravljati
merilo nad poslom koji niko nije opisao je merenje tišine.

**Druga:** zamalo sam napisao da priručnik visi o agentu, jer tako izgleda prirodno —
„Lazar zna Python". Ne zna Lazar Python; zna model. Lazar je stolica. **Kad opis posla
zalepiš za osobu, izgubiš ga onog dana kad osoba ode** — a agenti odlaze i dolaze
mnogo brže od ljudi.
