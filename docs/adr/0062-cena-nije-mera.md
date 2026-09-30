# ADR-0062 — Cena nije mera. Kočnica je „nema napretka"

- **Status:** prihvaćen (30.09.2026.)
- **Prethodi:** ADR-0044 (tri brojke), ADR-0050 (naš kvar je pojeo pokušaj),
  ADR-0061 (agent stao jer bi morao da pogađa), ADR-0026 (ključ po agentu),
  ADR-0033 (pravilo nula)
- **Menja:** ADR-0044 §2 — `PLAFON_CENTI` 60 → 300, `NAJVISE_POKUSAJA` 3 → 8;
  redosled kočnica se izričito preuređuje
- **Canon:** §13.1 (novac u centima, nikad float), §9.5 (poverenje), §6.4

## Šta se desilo

30.09. Slobodan je rekao:

> „Nije važno koliko košta. To su centi u pitanju, nisu dukati. Važno je da ovo
> uradimo kako treba."

To nije dozvola za rasipanje nego **uklanjanje opravdanja**. Nekoliko naših
granica nije imalo drugi razlog osim cene, a i dalje su radile — jer se broj, kad
se jednom upiše, više ne čita zajedno sa rečenicom koja ga je opravdala.

Šta je zaista bilo opravdano cenom:

| granica | gde stoji | razlog | šta je ostalo od razloga |
|---|---|---|---|
| 3 pokušaja po zadatku | `pisac.NAJVISE_POKUSAJA` | „plaća se ishod, ne trud" (ADR-0044 §2) | rečenica opravdava **način brojanja**, ne broj 3 |
| 60 centi po zadatku | `pisac.PLAFON_CENTI` | plafon troška | izmereno: nikad se ne javi prvi, pa ništa i ne brani |
| ključ samo trojici | dogovor od 30.09. | „dok se ne izmeri dnevni trošak" | trošak je izmeren i iznosi cente |

Izmereno 30.09. (`ucinak --persona P-00027`): **96 centi na 17 zakrpa** — 6 centi
po pokušaju, najskuplji viđeni poziv 9 centi. Tri pokušaja su najviše 27 centi.
**Plafon od 60 centi nikad nije mogao da se javi pre plafona pokušaja.** Stajao je
u kodu, u ADR-u i u testu, a nije branio ništa.

Broj pokušaja jeste branio — i to dva puta od agenta, zbog nas:

- **ADR-0050:** naša ponovna predaja je pojela P-00027 treći od tri pokušaja.
- **ADR-0061:** naš brif mu je sakrio `common/enums.py`, on je po pravilu nula
  odbio da pogađa — i to je knjiženo kao pokušaj 2 od 3.

Dva od tri pokušaja pojeli su **naši** kvarovi. Granica je bila postavljena da
čuva pare, a ono što je zaista radila jeste da agentu skraćuje posao kad mi
zgrešimo.

## Odluka

### 1. Redosled kočnica je odluka, i novac je poslednji

Do danas su tri prekidača u `pisac.zasto_ne` stajala jedan uz drugi bez rečenog
redosleda. Sad se redosled kaže naglas:

| red | kočnica | čemu služi |
|---|---|---|
| 1. | **nema napretka** | ista zakrpa dvaput, ili dve uzastopne iste pale kapije — agent melje |
| 2. | **broj pokušaja** | patološka petlja koju prva ne vidi: kapije se naizmenično menjaju (A, B, A, B) |
| 3. | **plafon troška** | kvar koji troši (petlja u rutu, pogrešan model, odbegli radnik) |

Prva je jedina koja sme da zaustavi ispravan rad. Druge dve su tu za kvar. Zato:

- `NAJVISE_POKUSAJA`: **3 → 8**. Osam ostavlja mesta i za nekoliko naših kvarova,
  a ne oslobađa agenta koji melje — njega hvata prva kočnica, na drugom pokušaju.
- `PLAFON_CENTI`: **60 → 300**. Nije procena potrebe nego namerno visoko: po
  izmerenoj ceni osam pokušaja je najviše 72 centa, pa plafon ostaje iznad punog
  posla i javlja se samo kad nešto nije u redu.

### 2. Da plafon nije prva kočnica — provera, ne obećanje

Odnos dva broja postaje **provera** (`test_plafon_nije_prva_kocnica`):

```python
NAJSKUPLJI_POKUSAJ_CENTI = 9          # izmereno, ne procenjeno
assert pisac.PLAFON_CENTI > pisac.NAJVISE_POKUSAJA * NAJSKUPLJI_POKUSAJ_CENTI
```

Kad ruta postane skuplja ili se digne broj pokušaja, test padne. To je i poenta:
tada se **diže plafon**, ne krati agentov posao. Bez ove provere odluka bi živela
samo u ovom fajlu, a brojevi u kodu bi tiho otišli svaki na svoju stranu.

### 3. Testovi granice predaju izričito

`test_plafon_pokusaja` i `test_plafon_troska` su do danas tvrdo upisivali poslovni
broj (`"(3/3)"`, `60`). Takav test meri **broj**, ne kočnicu: promena broja ga
obara iako je mehanizam ispravan, pa broj počinje da se brani testom umesto
ADR-om. Sad primaju `najvise=3` / `plafon_centi=60` kao ulaz, a podrazumevane
vrednosti čuva jedan test koji za to i postoji (`test_podrazumevane_brojke`).

Isti popravak je zatvorio i tihu rupu: `test_rucna_predaja_ne_trosi_pokusaj`
predaje tri zakrpe i tvrdi da plafon nije dosegnut. Pod novih 8 to bi bilo istinito
i da je brojanje pokvareno — **provera bi bila zelena a ne bi merila ništa**, isto
kao 30.09. u `apps/behaviour` (ADR-0061, mutaciono ispitivanje).

### 4. Ključ ide agentu koji ima posao, ne trojici jer je skupo

Hedž „tri, ne trideset tri, dok se ne izmeri dnevni trošak" otpada — trošak je
izmeren. Ali iz toga **ne** sledi da ključ ide svima. Izmereno stanje firme
30.09.: 33 agenta, 33 sa rutinom, **9 sa ijednom dozvolom**, 2 sa ključem, **1 sa
oba** (Lazar).

Nova granica, i ona merena a ne osećana: **ključ dobija agent koji ima dozvolu.**
Ključ bez dozvole je mogućnost trošenja bez mogućnosti rada; dozvola bez ključa je
posao koji se ne može odraditi — a P-00002 je danas prvo, P-00031 drugo.

Ovim odlukom dobijaju ključ **Réka, Amina i Teodora** (lanac sakupljanja znanja,
ADR-0059) i ostali iz onih devet. P-00002 se rešava sa druge strane: ne ključ nazad
nego dozvola, ili se ključ povlači.

### 5. Šta se ovim **ne** menja

Sve granice koje nisu bile o novcu ostaju iste, i to se kaže zato što je najlakše
pod ovakvim uputstvom popustiti sve odjednom:

- **Prekidač „nema napretka"** — nedirnut. Agent koji melje i dalje staje na
  drugom pokušaju. Uputstvo je bilo o ceni, ne o kvalitetu.
- **`MAX_DIFF_ZNAKOVA = 20_000`** i **plafon brifa 200 KB** (ADR-0041 §1) — to su
  granice **uskosti zadatka** i količine konteksta, ne cene. Zadatak koji ne staje
  i dalje se **deli**, kao u ADR-0044; samo se više ne deli zato što je skup nego
  zato što je preširok.
- **ADR-0061 §4 (izvod enuma, ne ceo fajl)** — ušteda je bila u bajtovima budžeta
  koji drugi fajlovi traže, ne u centima. Ostaje.
- **ADR-0044: „automatsko podizanje plafona kad pokušaj ne uspe"** — ostaje
  odbačeno. Plafon se diže ADR-om, ne sam sobom kad zatreba.
- **`GLOBAL_EXTERNAL_ACTIONS_ENABLED=false`** — nema veze s cenom i ostaje dok ne
  padne odluka GO.
- **Provajder koji uči na našim podacima** — odbija se za svaku svrhu. To nikad
  nije bilo pitanje cene.

## Šta je odbačeno

- **Skinuti plafon troška sasvim.** Plafon nije samo štednja nego i jedina kočnica
  za kvar koji troši u petlji. „Nije važno koliko košta" važi za posao koji se
  radi, ne za petlju koja gori. Zato ostaje, samo visoko.
- **Podići brojeve „za svaki slučaj" na 50 i 5000.** Broj bez izmerenog razloga je
  isti kvar kao 60 i 3, samo u drugu stranu. Osam i 300 izlaze iz izmerene cene
  pokušaja i iz izmerenog broja naših kvarova po zadatku.
- **Dati ključ svoj trideset trojici.** Vidi §4 — granica je posao, ne cena.
- **Ostaviti 60 i 3 pa dizati zastavicom kad zatreba** (`--plafon`, `--najvise`).
  Zastavica postoji i ostaje, ali podrazumevana vrednost je ta koja radi noću, u
  redu, bez čoveka. Ono što se mora ručno podići nije podignuto.
- **Vratiti pokušaje koje su pojeli naši kvarovi.** Zvuči pravedno, a znači pisanje
  preko istorije. Ishod je već pripisan `SISTEM`-u (ADR-0053); merenje učinka to
  već odvaja od agentove greške. Ovde se ispravlja granica, ne prošlost.

## Posledice

- `apps/orchestration/pisac.py` — `PLAFON_CENTI = 300`, `NAJVISE_POKUSAJA = 8`,
  odeljak „Tri brojke" prepisan u redosled kočnica.
- `tests/test_pisac.py` — dve provere primaju granicu izričito, dve nove
  (`test_podrazumevane_brojke`, `test_plafon_nije_prva_kocnica`); ukupno **1105**
  (prebrojano, ne izračunato: ADR-0061 je stao na 1095, pa je 8 provera iz
  `test_behaviour.py` došlo posle njega — 1095 + 8 + 2).
- ~~P-00027 na `TSK-01M3Q5GV73QRFVXWAYHSNDCXKJ` ima **6 pokušaja od 8** umesto 1 od 3.~~
  **Ispravka 30.09. u 14:56:** taj zadatak je **DONE** od 30.09. — Lazarova zakrpa
  je prihvaćena (`120383f`) i grana spojena. Nova granica na njega ne deluje nego
  na prvi sledeći zadatak. Red je prepisan iz ADR-0061 („ima još jedan pokušaj od
  tri") bez provere da se stanje u međuvremenu promenilo; `pisac --zasto` bi to
  rekao za dve sekunde.
- Ključevi za Réku, Aminu i Teodoru — ljudska ruka, posle prihvatanja.
- **Otvoreno ovim:** ADR-0061 je odbacio alat „pročitaj fajl kad ti zatreba" uz
  obrazloženje „svoja odluka sa svojim troškom". Trošak više nije argument; ostaje
  onaj drugi (krug razgovora umesto jednog poziva, ADR-0044). Odluka je otvorena i
  traži svoj ADR.

## Zapisano za ADR-0033

**Prva:** broj upisan u kod nadživi rečenicu koja ga je opravdala. `60` i `3` su
stajali u kodu, u ADR-u i u tri testa — a razlog („centi su, čuvajmo ih") prestao
je da važi tog dana kad je izmereno da su to zaista centi. Ništa nije pisnulo.
**Granica bez merenja ne stari vidljivo**; stari tiho i radi dalje. Zato §2 odnos
dva broja pretvara u proveru: kad razlog padne, pada i kapija.

**Druga:** rečenica pored broja nije isto što i opravdanje broja. „Plaća se ishod,
ne trud" opravdava **kako se broji** (zakrpe, ne pozivi) i savršeno zvuči pored
broja 3 — koji ne opravdava. Ja sam to napisao u ADR-0044 i posle pola meseca
čitao kao da je broj obrazložen.

**Treća:** granica koju je postavio strah od troška je dvaput kaznila agenta za
**naš** kvar (ADR-0050, ADR-0061). Kad se štedi na pogrešnom mestu, cenu plati
onaj ko nije birao — a mera učinka zabeleži njegovo ime.

**Četvrta:** uputstvo „nije važno koliko košta" bilo je najlakše sprovesti kao
popuštanje svega. §5 postoji zato što popuštanje nije poslušnost: od šest granica
koje su izgledale kao štednja, tri su bile o uskosti zadatka i kontekstu, a ne o
novcu. **Kad padne jedan razlog, proverava se koja granica je na njemu stajala —
ne dižu se sve ruke.**

**Peta** (dopisano 30.09. u 14:56, posle sopstvene greške u ovom istom ADR-u):
posledicu sam prepisao iz ADR-0061 umesto da je izmerim, a između dva ADR-a je
zadatak završen. **Rečenica iz jučerašnjeg dokumenta je tvrdnja o jučerašnjem
stanju**, ne činjenica — i kad se prepiše bez provere, dokument koji beleži naše
kvarove i sam postane jedan.
