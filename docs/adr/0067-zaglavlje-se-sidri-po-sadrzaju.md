# ADR-0067 — Zaglavlje hunka se sidri po sadržaju, jer tako radi i `git`

- **Status:** prihvaćen (01.10.2026.)
- **Prethodi:** ADR-0066 (rep se dopunjuje iz fajla), ADR-0065 (hunk mora da ima
  rep), ADR-0052 (zaglavlje se prebrojava), ADR-0053 (čija je greška),
  ADR-0033 (pravilo nula)
- **Menja:** ADR-0066, odeljak „Zašto ovo nije pogađanje" — druga alineja se
  **ispravlja**: pozicija iz zaglavlja nije pouzdana i ne sme da bude ulaz
- **Canon:** §6.4 (izvršni ugovor)

## Šta se desilo

Zakrpa 6 na `TSK-01M3V1NV6S82R25AMH8E6JWYNK` je prva prošla kroz dopunu iz
ADR-0066. Dopuna je prijavila uspeh:

> `tests/test_lessons.py`: hunku u redu 31 dopisano 1 red(ova) konteksta iz
> fajla (redovi 194–194)

A poslušnik ju je odbio: `patch failed: tests/test_lessons.py:186`.

Izmereno nad pravim `git`-om i pravim fajlom, pre nego što je išta zaključeno:

| mera | nalaz |
|---|---|
| telo hunka (4 reda konteksta + 4 obrisana) | tačno, bajt po bajt |
| gde to telo zaista stoji u fajlu | red **201** |
| šta je model deklarisao u `@@` | red **186** |
| koji je red dopuna dopisala | red **194** — docstring drugog testa, 7 redova iznad pravog mesta |

Isto telo, četiri varijante zaglavlja i repa, nad istim fajlom:

| zakrpa | `git apply --check` |
|---|---|
| sirova: `@@ -186`, bez repa | odbija |
| naša dopunjena: `@@ -186`, rep iz reda 194 | **odbija** |
| `@@ -186`, ali **ispravan** rep (red 209) | **prolazi** — `offset 15 lines` |
| `@@ -201`, ispravan rep | prolazi |

Tu je sve. **`git` ne čita broj iz zaglavlja — traži telo po sadržaju i sam
prijavi pomeraj.** U istoj zakrpi je i hunk za `apps/content/lessons.py` prošao
sa `offset -3 lines`, i niko to nije ni primetio.

Dakle: agentova pogrešna pozicija **nije koštala ništa**. Jedina njegova greška
je bio izostavljen rep. Naša dopuna je toj cifri poverovala, pročitala fajl na
pogrešnom mestu i na ispravno telo zalepila tuđi red — i tako od bezopasne
greške napravila zakrpu koja se ne primenjuje nigde.

## Odluka

### 1. `zakrpa.usidri` ide prvi, pre svega ostalog

Za svaki hunk se uzmu stari redovi (kontekst + obrisani) i **traže u fajlu**.
Ako se nađu na **tačno jednom** mestu koje nije ono iz zaglavlja, zaglavlje se
pomera tamo — i stara i nova strana za isti pomeraj.

Redosled u `check` je sada: `paths_in` → **`usidri`** → `dopuni_rep` →
`prebroj_hunkove` → `proveri_rep` → `may_touch`. Sidrenje mora biti prvo, jer
sve posle njega čita fajl „na poziciji iz zaglavlja".

### 2. Pomera se samo kad je nalaz jedinstven

Nula mesta ili više njih — ništa se ne dira i zakrpa pada kao i do sada.
Poziciju ne biramo nego je nalazimo; jedinstven nalaz nije izbor. `NAJMANJE_SIDRA
= 2`: hunk koji nudi jedan stari red se ni ne traži, jer se jedan red u fajlu
ponavlja prelako.

### 3. Sidrenje se uvek vidi

`Nalaz.sidra` → `reason` → `audit`, istom logikom kao ADR-0052 i ADR-0066.
Poruka kaže šta je zaglavlje tvrdilo, gde telo stvarno stoji i koliki je pomeraj.

### 4. Poruka o repu je **i sama** pokazivala pogrešan red

`proveri_rep` računa gde rep treba da stoji iz istog deklarisanog broja:
`kraj_hunka = pocetak + starih - 1`. Zato je poruka koju je agent dobio na
pokušajima 4 i 5 glasila „dodaj bar 1 red konteksta (red **194** fajla)" — a
red koji tamo ide je **209**. Rekli smo mu tačnu stvar i pogrešno mesto.

Izmereno posle izmene, nad istim ulazom:

| | poruka pokazuje na |
|---|---|
| bez sidrenja | red 6 |
| sa sidrenjem | **red 13** (tačan) |

Pošto `usidri` u `check` radi pre svega, `proveri_rep` od sada gleda usidreno
zaglavlje i njegova poruka nosi pravi broj. Popravka nije nova — ista izmena
leči oba mesta — ali zasluga za pokušaje 4 i 5 time **nije** cela agentova:
suština uputstva je bila tačna, pokazivač nije.

### 5. Priručnik se **ne** menja

Izmereno je da `git` toleriše pogrešan broj. Pravilo koje bi agentu nalagalo da
tačno broji redove rešavalo bi problem koji ne postoji, a zauzimalo bi mesto u
budžetu priručnika (ADR-0063). Pravilo 2 već traži ono što jedino i fali — rep.

## Šta je odbačeno

- **Odbiti zakrpu kad je pozicija pogrešna.** To bi bilo strože od `git`-a, nad
  zakrpom koju `git` primenjuje bez reči. Provera strožija od alata koji presuđuje
  nije provera nego naša navika (ADR-0065, lekcija prva).
- **Dozvoliti sidrenje po delimičnom poklapanju (fuzz).** `git` to ume, mi nećemo:
  delimično poklapanje ima stepene, a stepen je mesto na kom se pogađa.
- **Ukinuti `dopuni_rep` i vratiti se na ADR-0065.** Dopuna nije bila pogrešna
  nego slepa. Sa sidrom ispred sebe radi tačno ono zbog čega je uvedena.
- **Ispraviti ovu zakrpu rukom i zatvoriti zadatak.** Isto što i 01.10. u podne:
  posao koji uradi čovek ne meri agenta (ADR-0060 §6).

## Posledice

- `apps/orchestration/zakrpa.py` → `usidri`, `NAJMANJE_SIDRA`, pomoćne
  `_telo_hunka` i `_stari_redovi` (tri funkcije su do sada sekle telo hunka
  svaka za sebe), polje `Nalaz.sidra`, upis u `reason` i `audit`.
- `tests/test_zakrpa.py` → 9 novih provera; ukupno **1163**.
- `TSK-01M3V1NV6S82R25AMH8E6JWYNK` — **zatvoren 01.10. u 17:20**, commit
  `ae167e390c3c10599b4b869a12f7fe29c46b3aaa`, **sedam pokušaja, 42 centa od
  300**. Sedmi je prošao iz prve posle sidrenja, i sidro je radilo na oba
  hunka: `lessons.py` −3, `test_lessons.py` +16. Model opet nije pogodio
  nijednu poziciju — što je i cela poenta: `git` ih ne čita, pa ni mi ne
  smemo da ih čitamo kao istinu.
- Raspodela sedam pokušaja: 1–3 pala na **netačno pravilo 2** priručnika
  (ADR-0065), 4–5 na uputstvo koje je pokazivalo **pogrešan red** (§4 iznad),
  6 na **našu dopunu sa tuđeg mesta** (ovaj ADR), 7 prošao. Jedini deo koji
  pripada agentu je to što na 4 i 5 nije dodao **nijedan** red konteksta,
  iako mu je suština uputstva bila tačna.

## Zapisano za ADR-0033

**Prva:** ADR-0066 je tvrdio da dopuna „ne može tiho da promaši: ili se sve
poklopi, ili pukne kao pre". Ishod jeste bio pucanje — ali je `reason` prijavio
**uspešnu dopunu**. Dnevnik je rekao da smo pomogli, a zalepili smo tuđi red.
**Mera koja prijavljuje svoj postupak, a ne svoj ishod, laže iako ne greši.**

**Druga:** tri dana sam gledao kako `git apply` odbija zakrpe, a nijednom nisam
izmerio **šta `git` zapravo čita**. Da sam prvog dana pustio ispravan rep sa
pogrešnim brojem, video bih `offset 15 lines` i znao bih da broj ne igra ulogu.
Umesto toga sam redom popravljao ono što sam pretpostavljao da `git` traži.
**Pre nego što alat poslušaš, izmeri šta od tebe traži.**

**Treća:** ADR-0065 je zabranio dopunu repa, ADR-0066 ju je uveo, ADR-0067 joj
dodaje uslov bez kog je štetna. Tri odluke o istoj stvari u devet sati. To nije
kolebanje: svaka je pala na meri koju prethodna nije imala. Ali je i znak da je
ovo mesto moglo da se izmeri odjednom, u jednom popodnevu, da sam merio alat
umesto svojih pretpostavki o njemu.

**Četvrta:** `.env.prod` je sve vreme stajao u indeksu `git`-a na serveru, iako
je u `.gitignore`. Jedan `git commit -a` i tajne odlaze na GitHub. Nisam ga
tražio — video sam ga slučajno, u ispisu koji sam zatražio zbog nečeg drugog.
**Ono što se ne meri redovno, nađe se slučajno ili nikad.**
