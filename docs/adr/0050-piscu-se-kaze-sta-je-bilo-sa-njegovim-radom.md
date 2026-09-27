# ADR-0050 — Piscu se kaže šta je bilo sa njegovim radom

- **Status:** prihvaćen (27.09.2026.)
- **Prethodi:** ADR-0041 (brif), ADR-0044 (pisac), ADR-0045 (nalaz), ADR-0047 (izvor
  fajlova), ADR-0048 (diff bez `git` zaglavlja), ADR-0049 (aritmetika hunkova),
  ADR-0033 (pravilo nula)
- **Menja:** ADR-0041 (`previous_patch`), ADR-0044 (brojanje pokušaja), ADR-0045
  (zatvaranje nalaza)

## Šta se desilo

Posle ADR-0049 je Lazar dobio četvrti pokušaj i **vratio doslovno istu pokvarenu
zakrpu**. Otisak ju je odbio, poziv je plaćen, 7 centi bačeno.

Brif koji je pri tom dobio, pročitan sa njegove strane:

```
previous_patch : { status: "ACCEPTED", applied_sha: "", paths: [...] }
failed_gates   : [ { gate: "pytest", detail: "apply --check: error: corrupt patch at line 22" } ]
open_findings  : []
```

Dakle: *tvoja zakrpa je prihvaćena, recenzija je prazna, a negde je neka `git`
poruka pod imenom `pytest`.* Iz tog brifa je vraćanje iste zakrpe razumna odluka.

Tri naše stvari su se ovde sabrale, i nijedna nije njegova:

1. **`ACCEPTED` znači samo „prošla je proveru putanja".** U brifu stoji kao
   „prihvaćeno", što je najjača poruka na ekranu i tačno suprotna istini.
2. **`open_findings` je prazno zato što sam ja 26.09. zatvorio oba nalaza kao
   `FIXED`** nad zakrpom koja se nikad nije primenila (ADR-0048). Recenzija zbog
   koje je ceo krug i postojao bila mu je nevidljiva.
3. **Razlog odbijanja do pisca nikad ne stiže.** `_prethodna` uzima samo
   `ACCEPTED`/`APPLIED` zakrpe. Tri odbijanja do sad — „nije vratio diff", „ista
   zakrpa", i od sutra `BAD_HUNK` — i nijedno mu nije pokazano. Poruka iz ADR-0049
   koja broji redove hunka bila bi savršeno beskorisna: pisac je ne vidi.

I četvrta, koja se videla usput: **plafon pokušaja je brojao redove u tabeli**, pa
je naša ponovna predaja njegovog ranijeg teksta (0 centi, nijedan poziv) pojela
treći od tri pokušaja.

## Odluka

### 1. Brif kaže ishod, ne status

`previous_patch` dobija polje `ishod` — rečenicu koju pisac čita pre statusa:

| stanje | `ishod` |
|---|---|
| `REJECTED` | `ODBIJENA je i nije ušla u kod. Razlog: <reason>` |
| ima `applied_sha` | `primenjena i zapamćena na grani zadatka (commit <sha>)` |
| `ACCEPTED`, merena, bez commita | `prošla je proveru putanja, ali NIJE primenjena — u kodu je nema` |

`status` i `reason` ostaju u odgovoru za mašine. `ishod` je za onoga ko piše.

### 2. Odbijena zakrpa ulazi u brif, sa razlogom

`_prethodna` prima i `REJECTED`, **bez uslova o kapijama**: odbijena zakrpa je
presuđena i kad je nijedna kapija nije ni videla. Prihvaćena a nemerena i dalje ne
ulazi — nju poslušnik tek uzima, pa se o njoj još ništa ne zna.

Razlog odbijanja je jedino po čemu pisac može da ispravi rad. Bez njega je svaka
naša provera — pa i aritmetika hunkova iz ADR-0049 — zid bez natpisa.

### 3. Plafon pokušaja broji pozive modelu

Novo polje `TaskPatch.from_model`, koje `pisac` postavlja na svakom svom putu.
`_zakrpe_modela` filtrira po njemu.

**Cena nije uzeta kao merilo**, iako bi danas radila: model koji ne košta
(sopstveni, lokalni — a to je plan) time bi dobio beskonačno pokušaja. Zatečeni
redovi su popunjeni po ceni jednokratno, u migraciji: to ne menja nijednu tvrdnju
(ADR-0046), nego upisuje činjenicu koja je u tim redovima već stajala, u polje koje
do sad nije postojalo.

Posledica na zatečenom zadatku: Lazar se vraća na **2 od 3**, što je i bio.

### 4. `reopen_finding` — zatvoren nalaz se vraća u igru

`close_finding` s pravom odbija `OPEN` kao cilj: zatvaranje je odluka, ne prekidač.
Ali pogrešna odluka mora da ima izlaz, inače greška u presudi postaje trajna, a
pisac radi nad praznom recenzijom — što se tačno i desilo.

Tri granice, iste kao kod ispravke tvrdnje (ADR-0046):

- **samo čovek** (`actor` mora da počne sa `user:`). Mašina koja nađe nešto novo
  piše nov nalaz, ne vraća stari;
- **izvršilac ne dira nalaz na sopstveni rad** (ADR-0034 §5.2) — ni da ga zatvori,
  ni da ga otvori;
- **razlog je obavezan**, i ide u zapis. Bez njega bi audit rekao da se status
  vratio, a ne zašto — a zašto je ono što sledeća recenzija mora da vidi.

Tvrdnja, težina i izvor se ne diraju. Zapis `task.finding.reopened` nosi stari
status, novi, i razlog.

Komanda: `manage.py nalaz --zadatak TSK-... --otvori <prefiks> --napomena "<razlog>"`.

## Šta je odbačeno

- **Brisanje ili prepravljanje lažne kapije `pytest`.** Zapis se ne doteruje
  (ADR-0046, ADR-0049). Ona ostaje; ono što se menja je da pisac sad pored nje vidi
  i šta se sa zakrpom stvarno desilo.
- **Preimenovanje `ACCEPTED` u nešto jasnije.** Enum nosi stanje u lancu provera i
  koristi se na više mesta; problem nije bio ime nego to što je reč stizala do
  pisca bez ikakvog objašnjenja.
- **Slanje svih ranijih zakrpa.** Plafon brifa je 200 KB i već se deli sa fajlovima
  (ADR-0047). Poslednja presuđena je ona koja se ispravlja.
- **Dozvoliti `OPEN` kao cilj u `close_finding`.** Funkcija koja i zatvara i otvara
  prestaje da bude odluka i postaje prekidač; a granice koje čuvaju ponovno
  otvaranje nisu iste kao one koje čuvaju zatvaranje.
- **Brojanje pokušaja po ceni.** Radi danas, ćuti onog dana kad model bude naš.

## Posledice

- `brif._ishod`, izmenjen `_prethodna`; `zadaci.reopen_finding`; `nalaz --otvori`;
  `TaskPatch.from_model` + `zakrpa.submit(od_modela=)` / `zabelezi_neuspeh(od_modela=)`;
  `pisac._zakrpe_modela`.
- **Migracija `0009_zakrpa_od_modela`** — dodaje polje i popunjava zatečene redove
  po ceni. Deploy traži `migrate`, koji `web` ionako vrti pri dizanju.
- 20 novih provera; ukupno 975.
- Jedan zatečeni test je promenio tvrdnju: `test_plafon_pokusaja` je punio plafon
  ručnim predajama, što više nije pokušaj. Sad predaje sa `od_modela=True`, uz nov
  test koji brani suprotno — da ručna predaja plafon **ne** troši.

## Zapisano za ADR-0033

Danas u 09:25 sam rekao: *„etiketa laže, ali sadržaj ne — pustiću ga tako."* To je
bila pretpostavka, doneta bez gledanja u brif, i koštala je 7 centi i jedan
pokušaj. Kad sam posle toga pogledao, u brifu su stajale dve poruke jače od te
etikete — `status: ACCEPTED` i prazni nalazi — i obe su bile naše.

Obrazac je isti četvrti dan zaredom, samo se pomerio: ranije su naše greške ulazile
u **meru** agentovog rada (ADR-0048, ADR-0049), sada se vidi da ulaze i u **građu**
od koje on radi. Mera koja laže kvari odluku; građa koja laže kvari sam rad.

I najgora pojedinost: nalazi su bili prazni zato što sam ih ja zatvorio kao
`FIXED`, a onda nisam napravio vrata da se to ispravi — pa je moja greška iz 26.09.
tiho radila i danas.
