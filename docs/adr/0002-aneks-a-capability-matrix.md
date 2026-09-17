# ADR-0002 — Capability & Compliance Matrix, Canon v1.1

- **Status:** prihvaćeno
- **Datum:** 16.09.2026.
- **Canon verzija:** 1.0 → 1.1
- **Izvor:** Aneks A — Capability & Compliance Matrix v1.0 (15.09.2026)

## Kontekst

Faza 11 (Runtime Integrations) traži da se capability matrica potvrdi
**neposredno pre razvoja adaptera**, jer nije tvrdnja o tome šta je dozvoljeno
nego interni model. Provera je urađena pre pisanja koda, na zvaničnoj
developer dokumentaciji svake platforme.

Osam nalaza menja dizajn. Najvažniji: **LinkedIn ne dozvoljava AI personu kao
lični profil** ni uz otvoreno označavanje — developer dokumentacija ima stavku
„No Fake/Headless Accounts", korisnički ugovor 8.2 zabranjuje profil „for anyone
other than yourself (a real person)". Drugi po važnosti: **odlazni engagement
ne postoji ni na jednoj platformi** — lajk tuđeg, follow i prvi DM nemaju API
put nigde.

## Odluka

Deset izmena, sve dodavanja ili sužavanja opsega. Nijedno ime iz v1.0 nije
preimenovano, nijedno polje uklonjeno, nijedna formula dirana.

| # | Izmena | Odeljak |
|---|---|---|
| A-01 | `IdentityVehicle` kao enum i polje; LinkedIn i Facebook samo `PAGE` | §3.14, §17.1 |
| A-02 | `DisclosureLabelStatus`; bez oznake nema `CONTROLLED_LIVE` ni `channel.*` akcije | §3.16 |
| A-03 | Capability `web.read_public` sa četiri obavezna parametra | §6.4, §12.6 |
| A-04 | Ishodi `PLATFORM_POLICY_REQUIRES_HUMAN` i `DISCLOSURE_MISSING` | §3.9 |
| A-05 | `sending_domain` odvojen od `persona_address`; najviše 3 mejlboksa po domenu | §12.8 |
| A-06 | Rate limit tabela bez „prvi DM" i „follow"; dodati web i X | §9.3 |
| A-07 | Cost bucket `x_api_credits` | §13.2 |
| A-08 | Trust L3 i L4 rezervisani — ne mogu se dodeliti | §3.11 |
| A-09 | LinkedIn: jedna Page po personi, imenovani super-admin | §17.1 |
| A-10 | TikTok i YouTube van pilota i van F6 | §16.2, §18 |

## Obrazloženje za sporne tačke

**A-08 (L3/L4 rezervisani).** Alternativa je bila ostaviti nivoe dodeljivim.
Odbijeno: nivo koji stoji u UI-ju a nema kanal na kom se izvršava navodi
operatora da misli da postoji put kojeg nema.

**A-09 (Page po personi, ne jedna zajednička).** Jedna MercatoMaster Page bila
bi jednostavnija za app review i administraciju. Odbijeno: persona ima sopstvenu
nišu, publiku i memoriju — spajanje u jednu Page brisalo bi razliku koja je ceo
smisao flote. Cena: pet Page-ova za administrirati, jedan app review koji ih
pokriva.

**A-10 (TikTok van opsega).** TikTok zabranjuje naloge vođene „in bulk" bez
obzira na označavanje, nema nijedan scope za interakciju, i nema čitanje za
komercijalne korisnike. YouTube zabranjuje automatizovanje objave bez izričitog
pristanka korisnika za tu radnju. Oba se vraćaju posle pilota kao poluautomatski
kanali sa čovekom u petlji, ne kao adapteri.

## Posledice

- Adapteri u F6 grade se za **LinkedIn, Meta i X**. TikTok i YouTube se ne pišu.
- `ChannelAccount` dobija `identity_vehicle`, `ai_disclosure_label_status`,
  `sending_domain`, `dkim_selector`, `warmup_started_at`, `daily_cap`.
- `channels/identity_vehicles.yaml` postaje DB constraint, ne dokumentacija.
- Trust ladder efektivno ima tri nivoa do daljeg.
- Pilot RACI dobija ulogu „super-admin LinkedIn Page-ova" kao zasebnu, ne kao
  dodatak postojećoj — to je i uslov app review-a i ono što popunjava izuzetak
  iz člana 50(4) EU AI akta (urednička odgovornost).

## Migracioni put

Kod pisan po v1.0 ostaje važeći; nedostaju mu samo nova polja. Nema
preimenovanja, nema destruktivnih migracija.

## Rok ponovne provere

**15.12.2026**, i obavezno pre razvoja svakog pojedinačnog adaptera, kao stavka
u definiciji gotovog za F6. U poslednjih dvanaest meseci X je dvaput promenio
model naplate, Meta dvaput ime profilne oznake, Cloudflare dvaput proširio
podrazumevanu blokadu, a EU AI akt ušao u primenu.
