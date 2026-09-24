# ADR-0034 — Departman za programiranje

- **Status:** prihvaćen (24.09.2026.)
- **Prethodi:** ADR-0017 (organizacija), ADR-0021 (plan), ADR-0022 (delegiranje),
  ADR-0014 (uredničke lekcije), ADR-0032 (izviđanje), ADR-0033 (pravilo nula)
- **Canon:** §3.11 (poverenje po capability-ju), §9.6 (kill-switch), §16.5 (audit)

## Zašto ovaj departman nije kao ostali

**Rezultat se proverava mašinski.** Nacrt objave traži čoveka da presudi; kod ne traži
— `pytest`, `ruff`, `canon_lint`, `makemigrations --check`. Ovo je jedini sektor u kom
agent ne mora da **tvrdi** da je uradio dobro, nego se to izmeri. Zato ovde odobrenja
smeju da budu najlakša — pod uslovom da je provera stvarna.

**Greška ne košta objavu nego sistem.** Loš nacrt se baci; loša migracija odnese bazu.

**Ovi agenti menjaju ono što ih ograničava.** Agent koji sme da dira `apps/policy` sme
da promeni sopstvena ograničenja. To niko drugi u korporaciji ne može, i oko toga se
gradi sve ostalo.

## Odluka

### 1. Sedam radnih mesta, svako zbog svog kvara

| Mesto | Nivo | Koliko | Zašto postoji |
|---|---|---|---|
| `SEF-RAZ` Šef razvoja | head | 1 | prima zahteve, deli na zadatke, prima eskalaciju |
| `RAZ-ARH` Arhitekta sistema | senior | 2 | piše ADR; **predlaže, nikad sam ne prihvata** |
| `RAZ-PRO` Programer | medior | 6 | piše kod po zadatku — ovde se skalira |
| `RAZ-REC` Recenzent koda | senior | 2 | **nikad nije onaj ko je pisao**; prvo pravila, pa model |
| `RAZ-TES` Testolog | medior | 2 | piše test koji **obara** grešku pre popravke |
| `RAZ-DEZ` Dežurni inženjer | medior | 2 | puštanje, incidenti, vraćanje unazad, logovi i trošak |
| `RAZ-BIB` Bibliotekar koda | medior | 1 | zavisnosti, licence, bezbednosne zakrpe |

Testolog je odvojen od programera namerno: **programer koji piše sopstveni test piše
test koji prolazi.** Recenzent je odvojen iz istog razloga iz kog odobravalac nije
predlagač.

### 2. Veština je `capability × nivo × opseg`

Poverenje je danas `(persona, capability)`. Za kod to nije dovoljno — isti programer
mora da bude `L1` u `apps/content`, a `L0` u `apps/policy`. Zato se uvodi **opseg**:
`(persona, capability, putanja)`.

Capability-ji sektora: `code.read`, `code.write`, `test.run`, `review.comment`,
`migration.write`, `dependency.add`, `deploy.stage`, `deploy.prod`.

### 3. Plan je razgovor — agenti ne ćaskaju

Razgovor između agenata je neograničen, bez traga, i sami sebe ubede u nešto. Mašina
koju već imamo je odgovor:

- Jedinica posla je **zadatak**: šta, zašto (link na ADR), **koje fajlove sme da dira**,
  i šta znači gotovo (koje kapije moraju da budu zelene).
- Predaja je **korak plana**, ne poruka (ADR-0022).
- Recenzija je **nalaz** — fajl, linija, tvrdnja, težina — a ne proza. Tako se broji i
  tako mašina može da postupi po njemu.
- **Ništa nije gotovo zato što agent kaže da jeste. Gotovo = kapije zelene.** To je
  pravilo nula (ADR-0033) primenjeno na kod.

### 4. Razgovor sa ostatkom korporacije

**Ulaz** je zahtev za izmenu sa **poslovnim razlogom, ne sa rešenjem.** Marketing kaže
„nacrt gubi srpske navodnike", ne „promeni liniju 40 u `lessons.py`". Arhitekta od
zahteva pravi predlog ADR-a; čovek odlučuje.

**Izlaz:** sektor koji je tražio dobija obaveštenje kad izmena krene. Uredničke lekcije
(ADR-0014) zatvaraju krug u drugom smeru.

**Eskalacija ide naviše, ne bočno:** programer ne prima naloge od marketinga direktno.

### 5. Šest tvrdih granica

1. **Nijedan agent ne menja ono što ga ograničava** — `apps/policy`,
   `apps/runtime/transport.py`, kill-switch, pisač audita, `common/enums.py`, Canon i
   sami ADR-ovi. Samo čovek. Bez ovoga je sistem dozvola pozorište.
2. **Nema samoodobravanja.** Recenzent nikad nije autor.
3. **Tajne se ne diraju.** `.env.prod`, `/secrets`, vrednosti iza `credential_ref`.
4. **Migracije su viša kapija.** Kod se vrati, obrisana kolona ne.
5. **Puštanje u produkciju je ljudska kapija** dok ne postoji izmeren učinak;
   staging je slobodan.
6. **Sve kroz git, ništa rukom na serveru** — svaka izmena vraćiva i potpisana.

### 6. Merenje — bez njega nema deset hiljada

Po agentu se vodi: zadaci završeni, **kapije prošle iz prvog puta**, nalazi recenzenta
na njegov rad, greške kasnije vraćene na njegov commit, trošak po zadatku. To je ono
što šefu-agentu daje sud o podređenom bez čovekovog čitanja koda.

## Šta je odbačeno

- **Ćaskanje između agenata** kao način dogovaranja. Plan i audit već rade taj posao.
- **Agent koji sam sebi odobrava izmenu**, u bilo kom obliku.
- **Paralelizam po broju agenata.** U jednom repozitorijumu granicu postavljaju
  **sudari**, ne glave: realno „jedan agent po oblasti koda u datom trenutku" — za ovaj
  repo petnaestak, ne hiljade. Deset hiljada ima smisla preko deset projekata i preko
  mnogo malih nezavisnih zadataka, ne unutar iste baze koda istovremeno.

## Posledice

- `seed_org` dobija sektor `RAZVOJ` i sedam mesta; `ekipa` dobija prvu smenu.
- Sledeći koraci, odvojeno: opseg u poverenju `(persona, capability, putanja)`, model
  zadatka sa spiskom dozvoljenih fajlova, i `open-code-review` kao prva kapija
  recenzenta (ADR-0032, presuda „uzimamo").
