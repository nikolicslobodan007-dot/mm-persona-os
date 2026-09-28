# ADR-0055 — Rečnik uz Pravopis: znanje u bazi, provera nad nacrtom

- **Status:** prihvaćen (28.09.2026.)
- **Prethodi:** ADR-0054 (kućni stil), ADR-0006 (F4 memorija i znanje), ADR-0033
- **Menja:** ništa — dodaje novi izvor znanja i novu proveru na izlazu

## Šta se desilo

ADR-0054 je stavio šest pravopisnih pravila u svaki prompt. Rečnik uz Pravopis
— drugi deo iste knjige, 174 strane, oko 8.800 odrednica — ostao je van sistema.
On ne može u prompt: plaća se po pozivu i ne bi stao ni da se plaća.

Ali rečnik ume nešto što pravilo ne ume: on **imenuje pogrešne oblike**.
„avlija (ne havlija)", „Antej (ne Antaj)", „podići, bolje nego podaći". To je
provera koju je moguće izvesti bez ijednog poziva modelu, i uz svaki nalaz
stoji odrednica i broj tačke.

## Šta je prvo palo

Juče sam iz skena izvukao rečnik razdvajajući odrednice **praznim redom**.
Izgledalo je da radi. Pre uvoza sam izmerio: od 174 strane, na **152** to nije
radilo — cele kolone su se slepile u blokove do 2.900 znakova, jer OCR na tim
stranama nije ostavio prazne redove. Da je uvezeno, agent bi na pitanje o jednoj
reči dobio pet zalepljenih odrednica.

Ono što stvarno razdvaja odrednice je **uvlaka**: u knjizi odrednica počinje uz
ivicu stupca, nastavak je uvučen oko 25 px na 300 dpi. Tesseract to daje u TSV-u,
sa `left` koordinatom svake reči. Leva ivica stupca se ne uzima kao najmanji
`left` (to je uvek mrlja ili linija reza, po kojoj bi ceo stubac ispao uvučen)
nego se računa iz 15. i 85. percentila raspodele, koja je dvogrba.

Cena: ponovni OCR 174 strane, oko sat vremena. Rezultat: **8.797 odrednica**,
medijana 37 znakova, 3,4% odstupanja od azbučnog reda (mereno ćiriličnom
azbukom — latinično preslovljavanje menja redosled i tu meru pokvari).

## Odluka

### 1. Broj tačke se ne pogađa

Deo PRAVILA ide do tačke 322. U rečniku ima **5.709 upućivanja**, i ona se dele
na tri slučaja:

| slučaj | primer | broj | šta se upisuje |
|---|---|---|---|
| izričito slovo pod-tačke | `т. 86d` | 3.193 | `86d` |
| poslednja cifra ne može biti slovo | `т. 179` | 1.688 | `179` |
| broj veći od 322 | `т. 854` | 39 | `85` — tačka sigurna, slovo nije |
| **dvosmislen** | `т. 276` | **789** | **ništa** |

Poslednji red je ono što je zamalo prošlo. Knjiga na str. 400 piše
„кубанска револуција, **т. 27b**"; OCR daje „т. 276". A tačka 276 postoji i
govori o nečem sasvim drugom. Po tekstu se ta dva ne razlikuju: `b` se čita kao
`6`, `d` kao `4`, `a` kao `2`.

Takvih 620 odrednica **nema broj tačke**, a u tekstu im stoji
`t. [nejasno: 276 ili 27b]`. Agent koji to pročita ne citira ništa, i to je
tačno stanje stvari. Izmišljeno upućivanje bilo bi gore od nikakvog: ono se
proverava, i onaj ko ga proveri nađe pogrešno pravilo pod tim brojem.

Ostaje **4.644 odrednice sa upućivanjem iza kojeg stojim.**

### 2. Rečnik ide u `KnowledgeSource`/`KnowledgeFact`, deljen

Jedan izvor (`persona=NULL`, `trust_score=1.0`), po odrednici jedna činjenica,
`predicate="pravopis.odrednica"`. U `object_json`: tekst (latinica i ćirilica),
tačke, strana, i oblici koje odrednica odbija.

Ponovni uvoz **briše i upisuje ponovo**, u jednoj transakciji. Knjiga se ne
menja, pa spajanje red po red ne bi ništa dobilo — a ostavilo bi odrednice iz
ranije, lošije obrade da žive pored novih. Baš to se umalo desilo.

### 3. Provera radi na izlazu, i prijavljuje — ne obara

`recnik.proveri(tekst)` poredi svaku reč sa spiskom od **330 oblika** (u 324
odrednice) koje knjiga izričito odbija. Bez modela, bez troška.

Tri stvari koje sam morao da ispravim, svaka nađena merenjem nad 36.733 reči
naših ADR-ova, ne razmišljanjem:

- **Padež.** Rečnik daje nominativ, rečenica ima „havliju". Poredi se osnova —
  reč bez najviše dva završna samoglasnika. Grubo, ali bez toga provera ne hvata
  skoro ništa.
- **Kvačice se ne skidaju.** Prvo sam ih skidao, kao kod traženja reči, pa je
  „podaci" prijavljivano kao „podaći" iz odrednice „podići, bolje nego podaći".
  To su dve reči i razlika je baš u kvačici. Kod traženja je tolerancija korisna;
  u proveri je greška.
- **Veliko slovo.** Odrednica „Koraks (ne Korak)" govori o prezimenu. Dok se
  veličina slova nije poštovala, provera je prijavljivala svaki „korak" u
  tekstu — 45 puta na 36.733 reči.

- **Zaštita koja je sve obarala.** Imao sam pravilo „oblik koji i sam ima svoju
  odrednicu nije zabranjen", da bi se izbegle obične reči. Knjiga pogrešnom
  obliku redovno daje **svoju** odrednicu koja upućuje nazad („havlija, ne nego
  avlija"), pa je pravilo obaralo baš najkorisnije slučajeve — među njima i
  „havlija", na kom sam proveru i pokazao, i koji nije prijavio ništa.
  Izbačeno: mereno nad 51 ADR-om (35.704 reči, bez ADR-0054 i 0055 koji sadrže
  same primere), sa zaštitom i bez nje ista su **4 pogotka**. Koštala je 22
  oblika i nije donela ništa.

Konačno: **4 pogotka na 35.704 reči (0,011%)**, od kojih su dva („Korak")
sporna u korist provere, a dva („mala", iz „mahala, ne mala") lažna.

Za takve postoji `manage.py recnik --utisaj mala --zasto "..."`: oblik se
isključuje iz provere, sa razlogom u zapisu
(`content.recnik.form_silenced`). **Odrednica se ne dira** — knjiga je tačna;
ukida se samo dejstvo u proveri.

### 4. Komanda

```
manage.py recnik --uvezi
manage.py recnik --stanje
manage.py recnik --nadji avlija
manage.py recnik --proveri "Ušao je u havliju."
manage.py recnik --utisaj mala --zasto "…"
```

`--uvezi` i `--utisaj` traže `--actor` koji počinje sa `user:`.

## Šta je odbačeno

- **Rečnik u prompt.** 8.797 odrednica; ni izbor od hiljadu ne bi stao, a izbor
  bi trebalo praviti po temi nacrta, što je pretpostavka o tome koje će reči
  model upotrebiti.
- **Automatska ispravka nacrta** („havlija" → „avlija"). Isto kao u ADR-0054:
  popravljač koji krije grešku onemogućava merenje koliko model greši. Prvo
  merenje, pa eventualno popravka, i to svojim ADR-om.
- **Pogađanje slova pod-tačke** po učestalosti (`854` → `85d` jer je `d` čest).
  Obrazac bi pogodio većinu i pogrešio na manjini, a manjina se ne bi videla —
  upućivanje izgleda isto kad je tačno i kad nije.
- **Odbacivanje odrednica bez broja tačke.** Broj tačke nije glavna vrednost
  rečnika; normativni oblik reči jeste. „bejzbol (bolje nego bezbol)" je koristan
  odgovor i bez upućivanja.
- **Prava morfologija** umesto sečenja samogljasnika. Vredi je uvesti kad se
  izmeri da grubo sečenje promašuje; do tada je to biblioteka i zavisnost zbog
  problema koji još nije izmeren.
- **Preslovljavanje izvornika.** U bazi stoje oba oblika. Agenti pišu latinicom
  (i primeri su latinični), ali ćirilični original je ono što se poredi sa
  knjigom kad neko proverava.

## Posledice

- `apps/content/recnik.py`, `apps/content/management/commands/recnik.py`,
  `apps/content/data/recnik-uz-pravopis.jsonl` (8.797 odrednica, 2,3 MB),
  `tools/pravopis/{tsv,odrednice}.py` — kako je datoteka napravljena.
- Bez migracije — `KnowledgeSource` i `KnowledgeFact` već postoje (ADR-0006).
- 34 nove provere; ukupno **1054**.
- Posle deploy-a treba jednom pokrenuti `manage.py recnik --uvezi`.
- **Nije urađeno:** provera se još ne zove iz `content.service.draft`. Kad se
  pozove, urednik će uz nacrt dobiti i nalaze; to je sledeći korak i biće rečeno
  kad bude gotov, a ne pre (ADR-0051).

## Zapisano za ADR-0033

Dva puta sam bio korak od uvoza podataka koje nisam proverio.

Prvi put: rečnik razdvojen praznim redom izgledao je uredno na strani koju sam
pogledao. Izmerio sam sve strane tek zato što sam hteo broj za ADR — i ispalo je
da 152 od 174 ne valja. **Uzorak koji sam pogledao nije bio nasumičan nego onaj
koji mi je prvi pao pod ruku.**

Drugi put: pravilo „broj veći od 322 znači da je poslednja cifra slovo" bilo je
tačno, ali sam ga primenio samo na brojeve van opsega. Da nisam otvorio sliku
strane 400 i uporedio red po red, „т. 276" bi ušlo kao tačno upućivanje.
**Obrazac se proverava na slučaju u kom ne radi, ne na onom u kom radi.**

Treći put — i ovaj je prošao. Proveru sam pokazao na rečenici „Ušao je u havliju",
i na serveru je ispisala **„Nema oblika koje Pravopis odbija."** Zaštita koju sam
dodao da bi se izbegle obične reči obarala je baš tu odrednicu. Testovi su
prolazili jer su radili nad izmišljenim odrednicama, a ne nad isporučenom
datotekom. **Provera nad lažnim podacima proverava kôd, ne podatke** — a pao je
podatak. Sada je u testovima i jedna tvrdnja nad samom isporučenom datotekom.

Pravilo koje iz ovoga sledi: **pre uvoza podataka izmeri se ceo skup, a uzorak
se poredi sa izvorom, ne sa samim sobom** — i **bar jedan test mora da dodirne
podatke koji se zaista isporučuju.**
