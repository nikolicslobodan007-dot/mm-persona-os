# ADR-0071 — Grana se čoveku prevodi, ne ispisuje

- **Status:** prihvaćen (03.10.2026.)
- **Prethodi:** ADR-0038 §6 (`main` menja ljudska ruka), ADR-0043 (rezultat ide u
  granu), ADR-0050 (pokušaj je zakrpa modela), ADR-0062 (kočnice), ADR-0033
  (pravilo nula)
- **Menja:** `manage.py grane` i `rezultat.za_pregled`; dodaje `zakrpa.brojke` i
  `pisac.pokusaja`
- **Canon:** §6.4, §20

## Šta se desilo

02.10.2026, posle spajanja prvog zadatka koji je prešao ceo put do produkcije,
Slobodan je rekao:

> **„Ja ne umem da pregledam kod."**

Cela konstrukcija stoji na tome da `main` menja ljudska ruka. Tu ruku sam gradio
pretpostavljajući da čita `diff`. Ne čita — i nikad nije rekla da čita; ja sam to
pretpostavio i nijednom nisam proverio. **Pretpostavka o čoveku je ista vrsta
kvara kao pretpostavka o alatu** (ADR-0033, ADR-0067).

Posledica nije teorijska. Kapija koju odobrava neko ko ne može da proceni ono o
čemu odlučuje nije kapija nego potpis. Potpis bez uvida je gori od nepostojeće
provere, jer stvara utisak da je nešto provereno.

Do sada je `manage.py grane` ispisivao: ime grane, prvih dvanaest znakova
commita, naslov zadatka, ime agenta, i — samo ako nešto nije u redu — pale kapije
i broj blokada. Sve činjenice koje su potrebne za odluku stajale su u bazi i
nijedna se nije ispisivala.

## Odluka

### 1. Ispis postaje prevod

Po grani se ispisuje ovoliko, i sve iz baze:

| red | odakle |
|---|---|
| `ZADATAK` | `CodeTask.title` |
| `ZAŠTO` | `CodeTask.why` — rečenica koju je čovek napisao kad je zadatak otvoren |
| `AGENT` | `Persona.display_name` |
| `DIRANO` | po fajlu: koliko redova dodato i obrisano (`zakrpa.brojke`) |
| `KAPIJE` | svaka tražena kapija pojedinačno, nad **tom** zakrpom (ADR-0040) |
| `TROŠAK` | pokušaja od plafona, centi od plafona |
| `RECENZIJA` | koliko nalaza, koliko zatvoreno, koliko otvoreno, koliko blokada |
| `NE SPAJATI` / `SMETNJI nema` | mašinski razlozi protiv spajanja, ili njihov izostanak |

Izmereno nad pravim podacima 03.10.2026:

```
GRANA     zadatak/TSK-01M406S1QVND3FXS37P1AG89CD  (eeeeeeeeeeee)
ZADATAK   TSK-… · Poruka o nedostavljivosti se razlikuje od no-reply posiljaoca
ZAŠTO
          Kad agent posalje ponudu na adresu koja ne postoji, posta vrati
          obavestenje o nedostavljivosti. Do sada je to nestajalo bez traga, pa se
          mrtve adrese u bazi kupaca nisu videle.
          (po ADR-0008)
AGENT     Mila Vuković (AI)  [P-00001]
DIRANO
          apps/channels/reply.py  +4 −3
          tests/test_mail_reply.py  +3 −1
KAPIJE    pytest: prošla  ruff: prošla  canon_lint: prošla  migrations: prošla
TROŠAK    1 od 8 pokušaja, 51 od 300 centi
RECENZIJA 5 nalaza — zatvoreno 5, otvoreno 0
SMETNJI   nema — kapije zelene, nijedan nalaz nije otvoren
```

### 2. Prikaz ne zove model

Ni jednom. Sve što se ispisuje postoji u bazi i izvedeno je iz nje. Prikaz koji
sastavlja model mogao bi da bude lepši i da **slaže**, a laž u prikazu je gora od
nikakvog prikaza: čovek bi odlučivao po rečenici koju niko nije merio. Provera
`test_ne_zove_model` obara ceo prikaz ako ikad neko pozove `gateway.generate`
odatle.

### 3. Mašina daje činjenice, čovek daje sud — i to piše u ispisu

Poslednji red je: *„Ovo su činjenice iz baze, ne ocena. Da li izmena treba da
postoji — odlučuje čovek."* To nije kurtoazija nego granica nadležnosti. `NE
SPAJATI` se javlja samo na ono što se da pročitati iz baze:

- commit na grani ne pripada nijednoj zapisanoj zakrpi;
- kapije nisu zelene nad ovom zakrpom;
- ima otvorenih nalaza, posebno blokada;
- zakrpu nije napisao model nego čovek — ne meri agenta (ADR-0050).

Procena rizika nije u tom spisku i neće biti. Nju i dalje piše recenzent, u
razgovoru, svojim rečima.

### 4. Pokušaji se broje na jednom mestu

`pisac.pokusaja` je nastao da bi prikaz brojao **isto** što i kočnica. Do danas
je `_zakrpe_modela(zadatak).count()` stajalo na četiri mesta; prikaz bi bio peto.
Dve kopije iste definicije su dve definicije koje čekaju da se raziđu.

### 5. `zakrpa.brojke` ne sme da obori ništa

Prikaz nije provera. Zakrpa koja je već prihvaćena i primenjena ne sme da postane
neprikazljiva zato što joj brojač ne ume da pročita jedan red — zato `brojke`
nigde ne diže izuzetak i na smeće vraća prazno.

Brojevi su mereni prema `git diff --numstat` nad pravim repozitorijumom, ne prema
našoj predstavi o njemu:

| slučaj | `git` | `brojke` |
|---|---|---|
| izmena | `2  1  menja.txt` | `2  1  menja.txt` |
| nov fajl | `3  0  novi.txt` | `3  0  novi.txt` |
| brisanje | `0  4  stari.txt` | `0  4  stari.txt` |

Brisanje je jedini netrivijalan: tamo je `+++ /dev/null`, pa ime fajla nosi `---`.
Prva verzija koju sam napisao to nije radila i brisanje bi prikazala kao `0 0`.
Našao ju je ovaj sto, pre nego što je išta isporučeno.

## Šta je odbačeno

- **Da prevod piše model.** Vidi §2. Ovo ostaje otvoreno za **recenzentov sud**
  — rečenicu koju piše onaj ko je rad pregledao, upisanu u bazu i prikazanu uz
  činjenice. To je sledeći ADR, sa svojim pitanjima: ko sme da je napiše, da li
  je i ona predmet revizije, i šta se dešava kad je nema.
- **Ispisivati i sam `diff`.** Nema svrhe: čovek koji ga ne čita ne dobija ništa,
  a čovek koji ga čita ima `git show`.
- **Skratiti `ZAŠTO` na jedan red.** To je jedina rečenica u celom ispisu koja
  kaže **zbog čega** posao postoji. Prelama se, ne seče.
- **Staviti ocenu „bezbedno za spajanje".** Mašina to ne zna. Rečenica koju
  mašina ne može da potkrepi, a čovek pročita kao dozvolu, gora je od ćutanja.

## Posledice

- `apps/orchestration/zakrpa.py` → `brojke`.
- `apps/orchestration/pisac.py` → `pokusaja`; četiri postojeća mesta prebačena na
  nju.
- `apps/orchestration/rezultat.py` → `za_pregled` nosi `zasto`, `adr`, `izmene`,
  `pokusaja`, `centi`, `nalazi`, `upozorenja`; pomoćne `_nalazi` i `_upozorenja`.
- `apps/orchestration/management/commands/grane.py` → prevod umesto spiska.
- `tests/test_zakrpa.py` → `TestBrojke`, 6 provera.
- `tests/test_rezultat.py` → `TestPrevodGrane`, 6 provera.
- `tests/test_nalaz.py` → `test_grana_se_ne_otvara` zamenjen (vidi niže).
- Ukupno **1186** provera.

## Zapisano za ADR-0033

**Prva:** `main` je preko noći stajao sa **palim testom**, i to mojim.
ADR-0070 je 02.10. uklonio branu iz `rezultat.zabelezi`. Ispravio sam proveru
koja je tu branu čuvala u `tests/test_rezultat.py` — i nisam primetio drugu, u
`tests/test_nalaz.py`, koja je čuvala isto. Tražio sam `OPEN_BLOCKERS` i našao
dva mesta; treće je pisalo samo `match="BLOCKER"`.

Zašto je prošlo: **pustio sam `pytest tests/test_rezultat.py tests/test_zadaci.py`
i to nazvao kapijom.** Priručnik za rad kaže „kapije pre svakog commita:
`pytest`…" — bez imena fajla, jer kapija je **pun prolaz**. Pustio sam podskup
koji sam sâm izabrao, i izabrao sam ga tako da pokriva ono čega sam se setio.

To je ista greška od 01.10, kad sam `pytest` u živom kontejneru proglasio
proverom — samo u drugom smeru: tada sam izmislio stroži postupak koji je lagao
da nešto ne valja, sada blaži koji je lagao da sve valja. **Provera koju sam
skrojio prema onome čega se sećam meri moje pamćenje, ne kod.**

**Druga:** grep za imenom koda (`OPEN_BLOCKERS`) našao je dva od tri mesta, jer
je treće pominjalo samo tekst poruke. Kad se uklanja ponašanje, ne traži se ime
konstante nego **ponašanje** — ovde bi `rezultat.zabelezi` kao obrazac našao sva
tri.

**Treća:** tri dana sam merio agente i pisao ADR-ove o tome kako im dajemo
netačna pravila, a nijednom nisam izmerio **može li čovek na kraju lanca da uradi
ono što od njega tražimo.** Mera je bila jedno pitanje i nikad je nisam postavio;
odgovor je stigao tek kad ga je Slobodan sam rekao. **Lanac se meri do kraja, a
poslednja karika je čovek.**
