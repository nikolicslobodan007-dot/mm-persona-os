# ADR-0045 — Nalaz koji piše čovek

- **Status:** prihvaćen (26.09.2026.)
- **Prethodi:** ADR-0036 §2 (mašina ne postavlja `BLOCKER`), ADR-0034 §5.2 (nema
  samoodobravanja), ADR-0035 §3 (gotovo = kapije), ADR-0043 (grana), ADR-0033
  (pravilo nula)

## Problem

ADR-0036 §2 kaže da `BLOCKER` postavlja **isključivo čovek**. Postojale su dve
posledice koje niko nije primetio dok prva prava recenzija nije zatrebala:

1. **Čovek nije imao čime.** Jedini put do nalaza bio je `manage.py recenzija
   --sarif`, uvoz iz alata. Jedina težina koja zaustavlja zadatak bila je
   nedostupna onome ko je jedini sme dati.
2. **Pravilo se moglo zaobići.** Ono nije živelo u servisu nego kao tabela
   preslikavanja u uvozniku. `zadaci.add_finding(severity="BLOCKER")` prolazilo
   je iz bilo kog izvora. **Pravilo koje je moguće zaobići nije pravilo** — samo
   čeka drugi put do iste funkcije.

Povod nije bio teorijski. Prva zakrpa koju je napisao agent (ADR-0044, Lazar
P-00027, 6 centi, sve četiri kapije zelene) tiho seče spisak pouka i **ne kaže
da je odsekla**. Sledeći u lancu je model koji piše nacrt — dobije skraćen spisak
i radi po njemu kao da je ceo. To je ADR-0033 doslovno, i to je `BLOCKER`.
Trebalo ga je upisati, a nije imalo gde.

## Odluka

### 1. `manage.py nalaz` — upis, spisak, zatvaranje

```
manage.py nalaz --zadatak TSK-… --spisak
manage.py nalaz --zadatak TSK-… --fajl <put> --linija N --tvrdnja "…" --tezina BLOCKER
manage.py nalaz --zadatak TSK-… --zatvori 1a2b3c4d --kako FIXED
```

Komanda odbija da se pokrene ako `--actor` ne počinje sa `user:`. Nalaz težine
`BLOCKER` koji bi upisao agent pokretanjem ove komande bio bi zaobilaženje kroz
druga vrata, a upravo to zatvaramo.

Nalaz se zatvara po **početku identifikatora**, kao commit u `git`-u; dvosmislen
prefiks se odbija, ne pogađa. Ceo UUID se ne prepisuje rukom — isto pravilo kao
za ULID (ADR-0033).

### 2. Pravilo se seli u servis

`zadaci.add_finding` odbija `BLOCKER` iz svakog izvora osim `IZVOR_COVEK`.
Uvoznik SARIF-a i dalje preslikava stepen niže (ADR-0036 §1) — sada su to dve
brave umesto jedne, i donja ne zavisi od toga da li se neko setio gornje.

### 3. Izvršilac ne zatvara nalaz na sopstveni rad

`zadaci.close_finding` odbija kad je `actor` jednak `agent:<izvršilac>`. Bez toga
bi `BLOCKER` bio ukras: agent koji ne sme da odobri svoj kod (ADR-0034 §5.2) ne
sme ni da skloni prigovor na njega.

Provera je po `actor`-u, ne po personi, jer se ovuda ne prolazi kao persona nego
kao pozivalac — isti oblik kao `granting_ceiling` (ADR-0037 §4).

### 4. Ko je napisao ljudski nalaz

`reviewer` ostaje prazan: čovek nije `Persona`. Ime stoji u auditu
(`task.finding.closed`, `task.finding.added`) preko `actor`-a. Nova kolona se ne
uvodi za podatak koji audit već nosi.

## Šta je odbačeno

- **Persona „Slobodan" da bi `reviewer` bio popunjen.** Čovek u tabeli agenata je
  laž koja se posle broji u `ucinak`.
- **Zatvaranje nalaza kao posledica zelene kapije.** Kapija meri da kod radi;
  nalaz kaže da radi pogrešnu stvar. Jedno ne zatvara drugo.
- **`BLOCKER` koji sam istekne.** Prigovor koji nestane od stajanja nije kapija.
- **Slobodan izbor izvora iz komandne linije** (`--izvor`). Tada bi „čovek" bio
  string koji svako ume da otkuca.

## Posledice

- `manage.py nalaz`; `zadaci.close_finding`, `zadaci.IZVOR_COVEK`.
- `tests/test_nalaz.py` (26 provera). Nema migracije — `ReviewFinding.status` i
  `source` postoje od ADR-0035.
- **Pet postojećih testova je moralo da se ispravi**, jer su postavljali `BLOCKER`
  sa `source="agent"`. Nisu bili pogrešni kad su pisani — oslanjali su se na rupu
  koja je tada bila otvorena. Zapisano jer je promena tvrdnje, ne popravka.
- Otvoren `BLOCKER` sada stvarno zaustavlja i `finish` i otvaranje grane
  (ADR-0043), i to je pokriveno testom, a ne samo namerom.

## Šta ostaje otvoreno

- **Nalaz upisan posle grane ne povlači granu nazad.** Grana koja je već
  napravljena ostaje; `BLOCKER` sprečava `finish` i sledeće otvaranje. Povlačenje
  grane bi tražilo brisanje tuđeg rada iz repozitorijuma i nije mehanizam koji
  želimo dok ga neko stvarno ne zatraži.
- **Agent još ne ume da popravi po nalazu.** Brif nosi otvorene nalaze
  (ADR-0041 §4), pa bi sledeći pokušaj trebalo da ih vidi — ali to nije izmereno.
  To je prvi sledeći test petlje.
