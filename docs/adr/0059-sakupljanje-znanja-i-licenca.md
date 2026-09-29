# ADR-0059 — Agent sme da sakuplja znanje, ali ne sme da ga uzme

- **Status:** predložen (29.09.2026.)
- **Prethodi:** ADR-0032 (izviđanje), ADR-0008 (čitanje javnog weba), ADR-0054 (pravilo
  bez izvora), ADR-0055 (bolje bez upućivanja nego sa pogrešnim), ADR-0033
- **Menja:** ADR-0032 — izviđač više ne donosi samo **presudu o alatu** nego i
  **upotrebljiv artefakt**; uz to dobija pravilo o licenci i put za ponovno pisanje
- **Canon:** §10 (memorija i poreklo), §6.4 (izvršni ugovor), §12.1 (redosled pristupa),
  §16.5 (audit), §21 (uslovi platformi)

## Šta se desilo

Slobodan je 29.09. pokazao svoju fejsbuk zbirku „Kodiranje": kratki snimci UI
komponenti sa stranica tipa `Code & Chill` i `Code XR`. Jedan od njih —
„Folding OTP input animation", šest sekundi — ima **86.000 pregleda i 410 lajkova**.
Ispod piše komentar `Code?`, a autor kod podeli kad mu se prohte.

Zahtev je bio jasan: **„HOĆU DA SAKUPLJAM ZNANJE za svoje AI Agente."** Da agent prati
te stranice, vidi šta se dešava, lajkuje, upiše komentar koji se traži i donese kod u
našu bazu.

Prvi deo tog zahteva je ispravan i nemamo ga. Drugi deo je nemoguć, i to je već bilo
zapisano — u ADR-0032, pod „Šta je odbačeno": *„Praćenje Fejsbuk profila. Zvanično
zatvoreno, nezvanično traži prijavljen nalog."*

**A ADR-0032 stoji u statusu „predložen" od 24.09. i nikad nije pokrenut.** Pet dana je
odgovor na ovo pitanje ležao napisan i neaktiviran. To je zasebna pouka, dole.

## Odluka

### 1. Nov capability: `knowledge.collect`

Čitanje javnog weba već postoji (`web.read_public`, L0, sa obaveznim
`robots_respected`, istinitim `user_agent_declared`, 1 zahtev u sekundi i
`conditional_get`). Ono što **ne postoji** je pravo da se pročitano **upiše u
korporativnu memoriju kao znanje.**

```
knowledge.collect:
  description: "Upis javno pročitanog u bazu znanja, uz izvor i licencu"
  min_trust_level: L1
  requires_approval_class: null
  requires_disclosure_label: false
  required_constraints:
    source_url_required: true
    license_required: true
```

`min_trust_level: L1`, ne L0. Čitanje ne ostavlja trag; **upis u memoriju ostavlja**, a
pogrešan zapis se posle godinu dana ne razlikuje od tačnog.

Nov `ActionType`: `knowledge.collect → [web.read_public, knowledge.collect]`.

### 2. Zapis bez izvora i licence se odbija

Isto pravilo koje već važi za pravopis (ADR-0054: pravilo bez broja tačke ne ulazi), sada
i za kod. Svaki zapis nosi **adresu, datum čitanja i licencu**, a licenca ide u jednu od
četiri kutije:

| Kutija | Šta znači | Sme li u klijentski projekat |
|---|---|---|
| `SLOBODNA` | MIT, Apache-2.0, BSD, ISC | da, uz obavezno navođenje |
| `ZARAZNA` | GPL, AGPL, SSPL, BUSL | **ne** bez zasebne odluke |
| `ZABRANJENA` | „sva prava zadržana", CC-BY-NC za komercijalno | ne |
| `NEPOZNATA` | licence nema | **ne** |

**„Nema licence" znači „nema dozvole", ne „slobodno je".** To je već zapisano u ADR-0032
§4 za alate; ovde važi i za svaki isečak koda.

Ovo je razlog zbog kog komentar `Code?` ne bi ni rešio problem: isečak dobijen u
komentaru dolazi **bez licence**. Autor ga je dao tebi, ne svetu, i ne smeš da ga staviš
na klijentov sajt.

### 3. Ono što se ne sme uzeti — piše se iznova, i to čistim rukama

Kad je komponenta zanimljiva a licenca `ZARAZNA`, `ZABRANJENA` ili `NEPOZNATA`, ne
prepisuje se i ne „prerađuje". Ide ovako:

1. Izviđač gleda **kako se ponaša** i piše opis ponašanja: šta korisnik vidi, šta se
   dešava na klik, koliko traje, kako izgleda. **U opisu nema ni reda tuđeg koda** — ni
   imena promenljivih, ni strukture fajlova, ni CSS vrednosti prepisanih iz izvora.
2. Opis ide **drugom agentu, koji izvor nije video**, kao običan zadatak (ADR-0038) sa
   kapijama.
3. Rezultat je naš kod, naša licenca, bez ikakve obaveze prema autoru.

Razdvajanje nije formalnost. Agent koji je video izvor ne može da ga „zaboravi" — ono što
bi napisao nosi tuđi izraz. Zato opis ponašanja i pisanje rade **dva različita agenta**, i
to se vidi u zapisu: `opisao: P-000xx`, `napisao: P-000yy`.

Granica je jasna i uska: **ponašanje se sme preuzeti, izraz ne.** Efekat presavijanja
polja za OTP nije ničije vlasništvo; tuđih sto redova jeste.

### 4. Izvori — gde kod zaista stoji

Snimak na Fejsbuku je **oglas za kod, ne kod.** Sam kod stoji tamo gde ga autor drži:

- **GitHub** — API, licenca u repou, pretraga po temi. Ključ kao `credential_ref`
  (60 zahteva na sat bez njega, 5.000 sa njim).
- **CodePen** — javni penovi.
- **Sopstveni sajt i njuzleter autora** — link stoji u opisu objave, jer autor od toga
  živi. Čita se po pravilima Aneksa A: istinit User-Agent, `robots.txt`, jedan zahtev u
  sekundi, **nikad prijava i nikad „prihvatam"**.
- **Čovek dobaci** (ADR-0032 §3) — slika ekrana ili link sa telefona. Ista kartica, ista
  merila, bez obzira ko je doneo trag.

### 5. Šta ostaje čoveku

Lajk, praćenje i komentar na tuđoj objavi **ostaju ljudski potez.** Agent priprema:
spisak objava, nađen izvor koda, licenca, predlog komentara. Slobodan klikne.

To nije kompromis nego jedini postojeći put: za lajk i komentar na tuđoj objavi **ne
postoji API** ni za profil ni za stranicu, a `channels/identity_vehicles.yaml` na
Fejsbuku dozvoljava samo `PAGE` i izričito zabranjuje `PROFILE` — i to kao ograničenje u
bazi, ne kao preporuku.

### 6. Lanac je od tri agenta, ne od jednog

Slobodan je opisao posao koji sam radi, korak po korak: *pogleda izvor, prosledi na
analizu, neko presudi da li nam treba, neko upiše u biblioteku, drugi to kasnije
koriste.* Taj lanac se ne izmišlja — **ekipa za njega već postoji u `ekipa.py`.**

| Korak | Radno mesto | Ko | Šta radi | Šta mu treba |
|---|---|---|---|---|
| 1. gleda izvore | `IST-ANA` | Réka Tóth — *„konkurencija, izveštaji"* | prati GitHub, CodePen, RSS; pravi karticu sa adresom i datumom čitanja | `web.read_public` (L0) |
| 2. presuđuje | `SEF-IST` | Amina Begović — *„tržište, konkurencija"* | **uzimamo · gledamo · ne treba**, uz razlog u jednoj rečenici, prema registru otvorenih problema (ADR-0032 §5) | `knowledge.collect` (L1) |
| 3. upisuje | `RAZ-BIB` | Teodora Vasić — *„zavisnosti, licence"* | proverava licencu, svrstava u četiri kutije, upisuje u biblioteku | `knowledge.collect` (L1) |
| 4. koriste | svi | — | čitaju iz biblioteke | `code.read` (L0) |

**Teodorina niša je doslovno „zavisnosti, licence".** Upisana je 21.09., pre nego što je
ovo pitanje uopšte postavljeno. Kapija za licencu iz §2 nije nov posao nego posao koji je
neko već dobio i nikad nije počeo da radi.

Prosleđivanje između njih ide kroz delegiranje (ADR-0022), kao svaki drugi posao — ne
kroz novu mašineriju. Presuda i upis su **dva odvojena poteza dva agenta**: onaj ko
odluči da nam nešto treba ne upisuje to sam, iz istog razloga iz kog izvršilac ne dira
nalaz na sopstveni rad (ADR-0045).

**Uslov koji se ne sme prećutati:** `LLM_REQUIRE_PERSONA_KEY=true` — svaki agent misli
sopstvenim ključem (ADR-0026). Danas ključ ima **samo P-00027**. Ova tri agenta ne mogu
da odrade nijedan korak dok ne dobiju svoje ključeve, i to je trošak koji ulazi u plan
pre prvog prolaza, ne posle njega.

## Šta je odbačeno

- **Automatizovan nalog za lajkove i komentare**, na bilo kom domenu. Nije stvar toga
  čija je firma nego čega nema: API ne postoji, pa jedini put je pregledač koji klikće iz
  tuđe sesije. To je `PLATFORM_EVASION` iz `hard_prohibitions` i Slobodanova sopstvena
  granica („ne rade ništa zabranjeno"). **Zabrana ostaje.**
- **Izmena Aneksa A §1 t.3 da bi lajk „postao dozvoljen".** Taj red nije naša odluka nego
  zapis činjenice. Promena reda u YAML-u ne pravi API. Odbijeno kao kozmetika nad
  merilom — isti razlog kao „red sa ispisom pobeđuje" u ADR-0058.
- **Sakupljanje bez licence, „pa ćemo videti".** Kod bez licence na klijentovom sajtu je
  naš problem, ne autorov, i izbija tek kad nešto krene naopako.
- **Isti agent gleda izvor i piše zamenu.** Brže, i briše jedinu razliku između
  „napisali smo svoje" i „prepisali smo tuđe".
- **Automatsko preuzimanje i pokretanje tuđeg koda** — ostaje odbijeno iz ADR-0032.
  Izviđač predlaže; kloniranje i pokretanje je ljudska odluka, na mašini na kojoj stoje
  ključevi.

## Posledice

- `policy/capabilities.yaml` — nov `knowledge.collect`, nov `action_types` unos.
  **Zaštićena zona**: menja se ljudskom rukom, ne agentovom (ADR-0034 §5.1).
- Nov model za kartice sa licencom, ili proširenje `KnowledgeFact` — odlučuje se
  merenjem, pošto se vidi koliko polja zaista treba.
- `manage.py izvidjanje --izvori | --pokreni | --presudi` (iz ADR-0032) dobija
  `--komponente` i `--licence`.
- **ADR-0032 prelazi iz „predložen" u „prihvaćen"** — ovaj ADR ga ne zamenjuje nego
  pokreće.
- **Dnevni plafon ostaje 60 čitanja weba po personi** (`rate_limits_per_persona_day`).
  Prvi prolaz je time ograničen i to je namerno: prvo merenje, pa onda obim.

## Šta se meri pre nego što se ovo proglasi uspelim

Ništa u ovom ADR-u još nije izmereno — ovo je odluka, ne nalaz. Prvi prolaz vraća četiri
broja:

| | |
|---|---|
| nađenih komponenti | ? |
| sa licencom `SLOBODNA` | ? |
| koje traže ponovno pisanje | ? |
| cena ponovnog pisanja po komponenti (centi) | ? |

Ako se ispostavi da je ponovno pisanje jeftinije od traženja i provere licence — a
Lazarova poslednja zakrpa je koštala **6 centi** — onda sakupljanje tuđeg koda uopšte
nije glavni put, nego pomoćni. **To je nalaz koji tek treba da se desi i ne sme da se
pretpostavi.**

## Zapisano za ADR-0033

**Prva:** odgovor na Slobodanovo pitanje bio je napisan 24.09. u ADR-0032 i stajao je
pet dana u statusu „predložen". Nisam ga pogledao pre nego što sam počeo da objašnjavam
zašto nešto ne može. **Dokument koji je napisan a nije pokrenut ne postoji u praksi** —
a ja sam ga imao u repou sve vreme.

**Druga:** rekao sam „rizik je tvoj lični nalog, na njemu visi Kolibica". Slobodan to
nigde nije rekao; ja sam pretpostavio da bi automatizacija išla preko njegovog naloga.
Argument je ostao tačan i bez toga, ali **pretpostavka je ušla u opomenu i opomena je
zbog nje promašila.**

**Treća:** tri dana rada na merenju su bila ispravna i nevidljiva. Slobodan je posle njih
rekao da mu nije jasno šta radimo. **Ako onaj ko odlučuje ne može da prepriča šta je
urađeno, nije problem u njemu.**
