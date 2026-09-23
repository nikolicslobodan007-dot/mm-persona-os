# ADR-0017 — Korporativna organizacija i dosije agenta

- **Status:** prihvaćeno
- **Datum:** 23.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §1, §3.1, §3.11, §5, §9.1, §17 · ADR-0014, ADR-0015, ADR-0016
- **Kod:** `apps/personas/models.py`, `apps/personas/org.py`,
  `apps/personas/management/commands/seed_org.py`, `apps/content/lessons.py`,
  `apps/content/models.py`, `policy/capabilities.yaml`, `console/`,
  `tests/test_org.py`

## Kontekst

Do sada je agent bio „persona koja piše". Za korporaciju od 10.000 agenata to
nije dovoljno: mora se znati **ko šta radi, ko kome odgovara i ko je za šta
zadužen** (odluka Slobodana, 23.09.). Uz to, agent koji treba da radi umesto
čoveka mora imati doslednu ličnu pozadinu — inače iz meseca u mesec zvuči kao
druga osoba, a slika mu ne odgovara opisu.

## Odluke

### 1. Organizacija: sektor → radno mesto → raspored

Tri tabele u app-u `personas` (Canon §1 ima tačno 12 app-ova, pa nema novog):

- **`Department`** — sektor, sa svrhom, šefom i **čovekom koji za njega odgovara**.
- **`Position`** — radno mesto: naziv, specijalnost, nivo (`OrgLevel`), poslovi,
  broj izvršilaca i `reports_to` (kome to mesto odgovara).
- **`Assignment`** — ko sedi na kom mestu i od kada. Istorija se ne briše:
  premeštaj zatvara stari raspored, ne briše ga, pa se uvek zna ko je šta radio
  kad je nešto objavljeno.

Devet sektora (potvrdio Slobodan, 23.09.): Uprava, Nabavka i dobavljači,
Prodaja i izvoz, Marketing i sadržaj, Korisnička podrška, Logistika i magacin,
Finansije, Istraživanje tržišta, Kvalitet i usklađenost.

### 2. Radno mesto nije dozvola

Ovo je najvažnija granica u celom ADR-u. Šef sektora ne dobija nijedno
poverenje time što je šef — poverenje ide po sposobnosti (Canon §3.11) i menja
se samo kroz policy. Organizacija kaže **kome ide predlog**, ne **šta sme**.

- Eskalacija ide agentu-šefu; ako šefovsko mesto nije popunjeno, ide čoveku
  koji odgovara za sektor.
- **Niko ne odobrava sam sebi**: ako lanac dovede do iste persone, prekida se i
  ide na čoveka. Isto važi za krug u lancu i za dubinu veću od šest.
- Odobrenje koje Canon traži od čoveka nijedan agent ne daje, ni kao šef.

### 3. Pouke urednika dobijaju treći nivo

Uz „jedan agent" i „cela firma" (ADR-0014) dolazi **sektor**. Domet je uvek
tačno jedan — CHECK ograničenje u bazi ne dozvoljava pouku koja je istovremeno
i lična i sektorska; šira odluka poništava užu. U promptu se vidi odakle
pravilo dolazi (`[svi]`, `[MARKETING]`, bez oznake = lično).

### 4. Dosije: modelovan, ne državni identitet

`PersonaDossier` uz personu: mesto rođenja, prebivalište, visina, težina,
građa, boja očiju i kose, frizura, porodični status, deca, hobiji i opis
izgleda za generisanje slike. Datum rođenja ostaje na `Persona.birth_date_model`.

Canon §17 ostaje na snazi i ovde je preveden u kod:

- nema matičnog broja, broja dokumenta ni tačne adrese — polja ne postoje, a
  upis nepoznatog polja se odbija;
- agent je modelovan kao odrasla osoba, najmanje **22 godine**; mlađi datum
  rođenja se odbija;
- mere imaju granice u bazi (visina 120–230 cm, težina 35–250 kg), da greška
  pri kucanju ne postane opis za sliku;
- svaka izmena podiže verziju i ide u audit (`persona.dossier.changed`).

**Šta ulazi u prompt:** sektor, radno mesto, specijalnost, poslovi, šef,
godine, mesto rođenja i prebivališta, hobiji — i izričita napomena da je to
pozadina, ne tema. **Visina i težina ne ulaze u tekst** — one služe slici
(ADR o slikama sledi).

### 5. Odgovor na poštu uvek traži odobrenje

Nalaz od 23.09.: prvi odgovor jednoj adresi tražio je A1, a **svaki sledeći
odgovor toj istoj adresi prolazio je sam** (`ALLOW` → izvršenje). Ništa nije
izašlo, jer je globalni prekidač zaključan, ali bi posle GO odluke izašlo.

`email.reply_inbound` od sada nosi `requires_approval_class: A2`, pa svaki
odgovor čeka čoveka. Prag se pomera tek kad kvalitet odgovora bude izmeren na
stotinak primera — i to promenom pravila, ne koda.

## Posledice

- Konzola dobija stranu **Organizacija** i karticu **Radno mesto i dosije** na
  strani agenta; raspoređivanje i dosije menjaju se klikom, uz audit.
- Novi agent se sada zapošljava, ne samo pravi: dobija mesto u sektoru, šefa i
  dosije. `seed_org` postavlja kostur i idempotentan je.
- Pouke mogu da važe za sektor, što je bio otvoreni zahtev iz ADR-0014.
- 436 testova (dodato 17 + 3 u konzoli).

## Šta ostaje za sledeći korak

Slike agenta (profilna i galerija): isti lik na svakoj slici, opis iz dosijea
kao osnov, oznaka da je AI, čuvanje prompta i modela uz svaku sliku. Pre toga
treba izabrati generator — cene i mogućnosti se proveravaju u trenutku odluke,
ne pamte se iz ranije.
