# ADR-0023 — Zapošljavanje agenta

- **Status:** prihvaćen
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0016 (sandučić prati status), ADR-0017 (organizacija i dosije)
- **Canon:** §2.2 (ID persone), §3.1 (status), §5 (osobine), §16.2 (SIMULATION), §17 (identitet)

## Problem

Prvi agent je nastao ručno pisanim seed-om od dvesta linija
(`seed_agent_001`). Drugi bi značio kopiranje tog fajla i menjanje imena u
njemu. Deseti bi značio deset kopija koje se razilaze. **Deset hiljada nije
moguće.**

A cilj firme je upravo to: agenti se zapošljavaju, ne programiraju.

## Odluka

Jedna komanda vodi agenta od praznog do spremnog za rad:

```
manage.py zaposli --ime "Jovan Ilić" --mesto URE-SR
```

Traži se samo ono što je stvarno lično — **ime i radno mesto**. Sve ostalo se
izvodi iz organizacije ili ima polaznu vrednost koja se kasnije menja.

Komanda pravi: personu (`DRAFT`), javnu oznaku i činjenicu „ovo je AI", 
biografiju iz radnog mesta, osobine, glas, stanje ponašanja, rutine radnog dana
i vikenda, sandbox nalog sa pravom čitanja, raspored na radno mesto — pa je
kroz **pravi prelaz statusa** vodi u `READY`, čime joj se po ADR-0016 sam otvara
sandučić.

### Četiri pravila

1. **Rađa se kao `DRAFT`, postaje `READY` kroz `lifecycle.change_status`.**
   Bez prečice: prelaz traži ulogu, razlog i ostavlja audit zapis, a sandučić
   nastaje istim putem kao kod prvog agenta.
2. **Radno mesto ne daje nijednu dozvolu** (ADR-0017). Novi agent ima `L0` na
   svemu i nijedan stvarni nalog — samo sandbox. Poverenje i kanali su zasebne,
   namerne odluke.
3. **Dvoje nisu isti čovek, ali isti ID uvek daje istog.** Osobine odstupaju od
   sredine najviše ±0,12, a odstupanje je izvedeno iz `public_id` — ponovno
   pokretanje daje iste brojke. Dovoljno da se dvoje ne poklope, premalo da
   neko ispadne iz karaktera firme.
4. **Ništa se ne izmišlja u tišini.** Dosije ostaje prazan dok ga čovek ne
   popuni (zastavice `--rodjen`, `--zivi`, `--datum-rodjenja`, `--visina`,
   `--tezina`); agent bez niša dobija upozorenje da mu World Engine neće naći
   nijedan relevantan događaj.

### Šta komanda ispisuje

```
P-00002 — Jovan Ilić (AI), Marketing i sadržaj / Urednik sadržaja, READY.
  odgovara: Mila Vuković (AI)
  poverenje: L0 na svemu — radno mesto ne daje nijednu dozvolu.
  sledeće: ključ modela, portret, pa poverenje po potrebi.
```

Uz nju ide i `manage.py seed_org --spisak`: koja radna mesta postoje i ko ih
drži — polazna tačka za `--mesto`.

## Šta je odbačeno

- **Kopiranje `seed_agent_001`.** Mila ostaje kakva jeste, sa svojim ručno
  pisanim memorijama i nišama; ona je referentni agent, ne šablon. Novi agenti
  idu kroz `hiring.hire()`.
- **Slučajne osobine.** Pravi bi agenta koji se menja pri svakom pokretanju
  seed-a. Odstupanje izvedeno iz ID-a daje raznolikost bez te cene.
- **Automatsko dodeljivanje poverenja po nivou radnog mesta.** To bi bilo
  tačno ono što ADR-0017 zabranjuje.
- **Automatsko pravljenje memorija.** Novi agent ne zna ništa i to je istina o
  njemu; pouke stiže iz rada i od urednika (ADR-0014), a firmino znanje vidi
  preko opsega (ADR-0020).

## Posledice

- Agent broj 3 do 10.000 je jedna komanda, a ne jedan fajl.
- Prvi novi agent posle Mile može odmah da bude njen izvršilac, čime se
  delegiranje iz ADR-0022 po prvi put proverava uživo.
- Otvoreno: niše se za sada zadaju rukom (`--nise`); kad ih bude previše,
  izvodiće se iz radnog mesta.

## Kod

- `apps/personas/hiring.py` — `hire()`, `next_public_id()`, `slugify_sr()`
- `apps/personas/management/commands/zaposli.py`
- `apps/personas/management/commands/seed_org.py` — `--spisak`
- `tests/test_hiring.py` (9 provera)
