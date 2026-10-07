# ADR-0077 — Korpus ulazi na prva vrata, a svaka činjenica zna odakle je

- **Status:** prihvaćen (07.10.2026.)
- **Povod:** interni dokument „App Ideas / Product Intelligence" (07.10.2026.)
- **Prethodi:** ADR-0074 (dvoja vrata), ADR-0076 (strana `Izvori`, pečat
  `ingested_at`), ADR-0059 (licenca se ne pretpostavlja), ADR-0055 (rečnik kao
  uzor uvoza), ADR-0033 (pravilo nula)
- **Menja:** ništa u kodu danas — ovo je odluka o redosledu i o poljima koja
  fale, pre nego što iko napiše zakrpu
- **Canon:** §10.4, §10.5

## Šta se desilo

Stigao je dokument koji predlaže ceo Product Intelligence sloj: ingestion
engine nad tuđim repozitorijumom, AI enrichment, Product Scout sa devet agenata,
Opportunity Score, Component Registry, Feature Graph, Product DNA i Mutation
Engine.

Najbolja rečenica u njemu je prva: vrednost nije u broju ideja nego u
**ponovljivoj strukturi specifikacije**. To se poklapa sa prioritetom koji je
Slobodan postavio — „prioritet je sakupljanje skilova za AI Agente" — pa ovaj
ADR uzima deo koji se tiče sakupljanja, a ostalo odbija sa obrazloženjem.

## Izmereno pre pisanja (07.10.)

| pitanje | izmereno |
|---|---|
| koja polja nosi `KnowledgeSource` | `persona`, `source_kind`, `title`, `uri`, `checksum`, `trust_score`, `is_active`, `retrieved_at`, `ingested_at`, `robots_allowed`, `license_box`, `license_note` (uz veze `facts` i `derived_memories`) |
| šta je `KnowledgeFact.provenance` | ravan niz znakova; izmerena vrednost na odrednici rečnika je `user_provided` |
| ima li igde commit ili putanja fajla | **nema** — ni na izvoru ni na činjenici |
| koliko izvora čeka u redu | **0**, posle jednokratne popravke 07.10. (rečnik 8.797 činjenica, Pravilo nula 1) |
| licenca App Ideas repozitorijuma | MIT, navedena u samom repozitorijumu |

## Odluka

### 1. Korpus ulazi na prva vrata; repozitorijum se ne preuzima

Predloženi „Repository Fetcher" je odlazak na tuđi server, dakle **druga
vrata** (ADR-0074 §2). `GLOBAL_EXTERNAL_ACTIONS_ENABLED=false` stoji do GO
odluke, i ovaj ADR je ne menja.

Put koji je otvoren danas: čovek donese materijal, a materijal uđe komandom
`vestina` ili stranom `Izvori`. Isti rezultat, bez otvaranja vrata za koja
nismo spremni.

### 2. Licenca se nosi uz materijal, sa imenom

App Ideas je MIT. To znači kutija `SLOBODNA` i `license_note` = `MIT`, uz
sačuvanu adresu izvora. Pravilo kuće stoji iznad svega ostalog: sakupljamo, ne
krademo, i tuđe ime ostaje uz tuđi materijal.

### 3. Commit i putanja fajla su stvarna rupa, ali se ne pravi unapred

Za korpus iz repozitorijuma `uri` izvora nije dovoljno — ista adresa daje
različit sadržaj u različitim trenucima. Fale `commit` i putanja fajla.

Ta polja se dodaju **u istom zadatku u kom prvi takav korpus zaista uđe**, ne
pre toga. Migracija za podatke kojih nema je ista greška kao `ingested_at` koji
niko ne upisuje (ADR-0076, ispravka od 06.10.).

### 4. Ideja i potražnja su dva različita signala i ne mešaju se

- **Signal ideje:** „ovo bi bilo zanimljivo napraviti."
- **Signal potražnje:** „imam konkretan problem i tražim rešenje."

Nikada u istoj činjenici. Danas u bazu ulazi samo ono što je veština ili
znanje; tržišni signal nije veština i nema svoj predikat dok se ne odluči koji
je.

### 5. Skor, registry i genom čekaju populaciju

Predloženih deset dimenzija 0–100 i prag 75/100 nemaju nijedno merenje iza
sebe. To je pretpostavka ugrađena u broj, i pravilo nula je odbija.

Component Registry, Feature Graph, Product DNA i Mutation Engine pretpostavljaju
populaciju proizvoda iz koje se vadi genom. Mi imamo jednu bazu koda. Genom se
pravi posle populacije, ne pre nje.

## Šta je odbačeno

- **Repository Fetcher danas.** Druga vrata, čeka GO.
- **Opportunity Score sa pragom 75.** Izmišljen broj.
- **Component Registry / Feature Graph / Product DNA sada.** Nema populacije.
- **Nov model „Problem Database".** `KnowledgeSource` + `KnowledgeFact` to već
  nose, dok se ne izmeri da ne nose.
- **Da dokument postane plan rada.** On je ulaz u odluku, ne raspored poslova.

## Posledice

- Redosled iz ADR-0074 ostaje: komanda → strana → **transkripcija**. Ovaj ADR
  ne preskače treći korak.
- Dokument se čuva kao izvor odluke.
- Kad prvi korpus iz repozitorijuma uđe, isti zadatak donosi i `commit` i
  putanju fajla.

## Zapisano za ADR-0033

**Prvo.** 06. i 07.10. tražio sam od agenta ispravku rada koji još nije bio u
glavnoj grani. Zakrpe se u privremenom prostoru slažu jedna na drugu, a brif
agentu služi fajlove iz glavne grane — treća zakrpa se zato nije ni primenila
(`patch does not apply`). Tri zakrpe, 18 centi, nijedan red koda u gitu. Pravilo:
**dok zadatak nije spojen, ispravka se ne traži**; ako rad nije upotrebljiv,
otvara se nov zadatak sa punim brifom i praznom gomilom. Nov zadatak je prošao
iz prvog pokušaja, 6 centi, sve četiri kapije zelene (1226 testova).

**Drugo.** Jednokratna popravka od 07.10. upisala je pečat na dva stara izvora
**pravo u bazu, bez ijednog audit zapisa**. Tako je jer `audit.record` nema
pokretača, a `api/audit.py` je zaštićena zona u koju agent ne sme. To je ista
rupa koju ADR-0076 §4 već imenuje. Nerešena je, traži zaseban ADR i ljudsku
ruku, i ovde stoji zapisana da se ne izgubi.
