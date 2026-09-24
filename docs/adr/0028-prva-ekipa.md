# ADR-0028 — Prva ekipa korporacije

- **Status:** prihvaćen
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0017 (organizacija), ADR-0023 (zapošljavanje agenta)
- **Canon:** §17 (identitet persone), §3.11 (poverenje po capability-ju)

## Problem

Organizacija je imala **jedanaest radnih mesta, od kojih devet šefovskih**.
Zahtev „po nekoliko agenata na svakom radnom mestu" tu nije mogao da se ispuni:
u stolicu šefa nabavke ne mogu da sednu dvojica, i ne treba da mogu.

Firma nije imala ljude koji rade — imala je samo ljude koji rukovode.

## Odluka

### Izvršilačka radna mesta u svakom sektoru

Uz svako šefovsko mesto ide i izvršilačko, sa `headcount_max` većim od jedan,
jer se posao deli po jeziku, tržištu i smeni: `NAB-REF` (3), `PRO-REF` (3),
`URE-SR` (2), `MKT-DRU` (2), `POD-SR` (3), `LOG-REF` (3), `FIN-REF` (2),
`IST-ANA` (3), `KVA-KON` (2), plus `UPR-ASI` (1).

Šefovska mesta ostaju za jednog. To nije formalnost: `manager_of` i
`escalation_target` (ADR-0017) računaju da iznad svakog izvršioca stoji tačno
jedan šef.

### Spisak ekipe je podatak, ne kod

`apps/personas/ekipa.py` je spisak od 22 agenta sa dosijeom svakog. Komanda
`manage.py seed_ekipa` ih zapošljava kroz isti `hiring.hire()` kao i prvog
agenta — `DRAFT` → `READY` kroz pravi prelaz statusa, `L0` na svemu, nijedan
stvarni nalog. Idempotentna je: agent koji postoji se preskače, puno radno
mesto se preskače **sa razlogom**, ostatak prolazi.

### Ko su

**Evropa, ne samo Srbija.** Imena su srpska, mađarska, slovačka, bošnjačka,
hrvatska i češka — onakva kakva se stvarno sreću u Vojvodini, Sandžaku i
susedstvu. Firma posluje u regionu i to se vidi na spisku imena, a ne u
fusnoti.

**Otprilike pola-pola.** Muškarci i žene su ravnomerno raspoređeni i po
sektorima i po nivoima; direktorka, šefica prodaje, šefica finansija i šefica
istraživanja nisu ustupak nego raspored.

**Sve je izmišljeno i dosledno** (Canon §17): nijedno ime nije uzeto od stvarne
osobe, nema državnog identiteta, svako ima najmanje 22 godine, a opis izgleda
je sintetički i ne opisuje nijednu stvarnu osobu.

## Šta je odbačeno

- **Nasumično generisanje imena i dosijea.** Dvadeset dva izmišljena čoveka
  treba da izgledaju kao ekipa, ne kao ispis generatora; raspored porekla,
  pola i godina je odluka, pa se i proverava testom.
- **Davanje ključa modela svima odmah.** Dvadeset dva ključa je dvadeset dva
  računa i dvadeset dva mesta curenja. Ekipa se zapošljava sada, a ključ dobija
  onaj ko dobije posao (ADR-0026).
- **Aktiviranje cele ekipe.** Svi ostaju `READY`: rade kad im se zada, ne bude
  se sami. Aktivira se onaj ko ima šta da radi, iz spiska agenata (ADR-0025).

## Posledice

- Firma ima 24 agenta i nijedno prazno radno mesto; delegiranje (ADR-0022) ima
  gde da se odvija u devet sektora, ne u jednom.
- Bez ključa modela nacrte bi im pisao lokalni šablon — komanda to kaže na
  kraju, da niko ne pomisli da ekipa piše dok ne dobije čime.
- Otvoreno: portreti za 22 agenta. Opis izgleda već stoji u dosijeu, pa
  `manage.py dosije --pokazi` daje gotov tekst za generator, jedan po jedan.

## Kod

- `apps/personas/ekipa.py` — spisak i `dosije_od()`
- `apps/personas/management/commands/seed_ekipa.py`
- `apps/personas/management/commands/seed_org.py` — izvršilačka mesta i `headcount_max`
- `tests/test_hiring.py::TestEkipa` (5 provera)
