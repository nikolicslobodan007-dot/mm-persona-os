# ADR-0032 — Izviđanje: agent koji prati nove alate

- **Status:** predložen (nema uslova koji ga blokira — prihvata se na reč „idemo")
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0017 (organizacija), ADR-0022 (delegiranje), ADR-0008 (čitanje javnog weba)
- **Canon:** §10 (memorija i poreklo), §16.5 (audit), §21 (uslovi platformi)

## Problem

Slobodan uveče slika ekran sa objava o novim alatima, prosleđuje ih na analizu i iz
toga izvlači ono što nama treba. 24.09. je tako prošlo osam alata: ghidraMCP, engram,
`alibaba/open-code-review`, screenshot-to-code, airship, Ruflo, Tel-Agent. Od osam, tri
vrede, jedan nosi licencu koja bi nas ujela, četiri ne diraju nijedan naš problem.

Posao se ponavlja, ima jasna merila i ne traži nijednu spoljnu dozvolu. To je posao za
agenta, a ne za čoveka u jedanaest uveče.

## Odluka

### 1. Izvor je repozitorijum, ne objava o njemu

Svih osam alata sa te večeri su **GitHub repozitorijumi**. Nalozi koji ih objavljuju
(„AI Agent News", „GithubSignals" i slični) su prenosnici: uzmu ono što je već izbilo na
GitHub-u i naprave snimak. Agent zato stoji na izvoru i vidi istu stvar **pre** nego što
rilić izađe, sa punim README-om, licencom i brojevima — umesto da čeka da mu neko
prepriča.

Uz to: Meta zvanično ne daje tuđe objave sa stranica. Dozvola za čitanje tuđeg zida
dobija se tek kroz reviziju aplikacije i za odobrene namene, a ono što se dobija lako
daje podatke *o* stranici, ne njen sadržaj. Jedini drugi put je prijavljen nalog, a
prijava znači prihvaćene uslove — i time ugovorni rizik koji smo isključili (Aneks A §5).

### 2. Izvori

- **GitHub REST API** — nova skladišta po temi u prozoru vremena, sortirana po prirastu
  zvezdica; izdanja projekata koje pratimo; aktivnost organizacija od interesa. Ključ
  ide u `.env.prod` kao `credential_ref`: bez njega je granica 60 zahteva na sat, sa
  njim 5.000.
- **Hacker News** (otvoren API) i **Product Hunt** — odatle je i „Product of the day"
  koji je iskočio na Tel-Agentu.
- **Sopstveni kanali autora** — njuzleter, blog, RSS — po pravilima Aneksa A: istinit
  User-Agent, `robots.txt`, jedan zahtev u sekundi, **nikad prijava i nikad „prihvatam"**.

### 3. Dva ulaza, jedna biblioteka

Izviđač prima i ono što **čovek dobaci** — slika ekrana ili link sa telefona. Kartica i
presuda su iste bez obzira na to ko je doneo trag. Time se ne gubi ono što Slobodan
ionako radi, a ne pravi se obaveza da agent stoji tamo gde mu nije mesto.

### 4. Merila — četiri, uvek ista

| Merilo | Šta se gleda |
|---|---|
| **Licenca** | MIT/Apache/BSD prolazi. **AGPL diže zastavicu** uz obrazloženje: mrežna usluga + izmene = obaveza objave izmena. SSPL, BUSL i sopstvene licence — zastavica. **Bez licene se ne dira**: nema licence znači sva prava zadržana. |
| **Zrelost** | zvezdice, starost, poslednji commit, otvorena pitanja, da li se sam zove alfa |
| **Da li nam treba** | poklapanje sa **registrom otvorenih problema** |
| **Cena probe** | jedna komanda, `docker compose`, ili traži GPU |

### 5. „Da li nam treba" se meri prema spisku, ne prema utisku

Registar otvorenih problema je tabela u sistemu, a ne u nečijoj glavi: telefon i govor,
recenzija koda, vizuelni uređivač, jeftin model koji ne trenira na podacima, obrada
videa, memorija agenata. **To je ono što od izviđača pravi našeg izviđača, a ne još
jedan njuzleter.** Njuzleter kaže šta je novo; izviđač kaže šta je novo *a nama fali*.
Zato je Tel-Agent iskočio, a ghidraMCP nije — ne zato što je lošiji, nego zato što
obrnuti inženjering nije na spisku.

### 6. Presuda

**uzimamo · gledamo · ne treba**, uz razlog u jednoj rečenici. Kartica ulazi u biblioteku
sa poreklom (adresa, datum čitanja) i sa brojevima **kakvi su bili tog dana** — zvezdice
i commitovi se menjaju, pa se ne pamte kao večna istina.

### 7. Ko to radi

Izviđanje je stalan posao **sektora istraživanja** (`SEF-IST` → `IST-ANA`), zadaje se i
vraća kroz delegiranje (ADR-0022) kao svaki drugi. Nedeljni pregled ide direktoru, ne
u još jednu fasciklu.

## Šta je odbačeno

- **Praćenje Fejsbuk profila.** Zvanično zatvoreno, nezvanično traži prijavljen nalog.
- **Automatsko preuzimanje i pokretanje.** Izviđač **predlaže**; kloniranje i pokretanje
  tuđeg koda je ljudska odluka. Na mašini na kojoj stoje ključevi to nije formalnost nego
  jedina odbrana od zaraženog paketa.
- **Zvezdice kao jedino merilo.** Popularnost se naduvava tačno onim rilićima zbog kojih
  ovaj ADR i postoji. Zato uz zvezdice idu poslednji commit, starost i otvorena pitanja.

## Posledice

- Koraci plana i kartice u memoriji; kad Libri (ADR-0031) bude gotov, kartice se sele
  tamo bez prepisivanja, jer je format isti.
- `manage.py izvidjanje --izvori | --pokreni | --presudi`.
- Dnevni plafon troška za čitanje README-ova, kao i za svaki drugi posao sa modelom.
- Prvi upis u registar otvorenih problema su ona tri nalaza od 24.09.:
  `open-code-review` (**uzimamo**), `airship` (**gledamo**, kad dođe red na pickstar.cloud),
  `Ruflo` (**gledamo**, zbog ideja, ne zbog zamene).
