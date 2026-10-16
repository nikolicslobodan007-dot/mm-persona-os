# ADR-0100 — Prelazak agenta u živo okruženje ima svoj put

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Posle ADR-0099 uži prekidač je upaljen, a nijedan agent ne može da
  pročita stranicu jer su svi u `SIMULATION` — i ne postoji način da se to
  promeni.
- **Prethodi:** ADR-0017, ADR-0099, Canon §8.5
- **Menja:** nova komanda `apps/personas/management/commands/okruzenje.py`.
- **Canon:** §8.5

## Izmereno

Agent nastaje u `SIMULATION`: `apps/personas/hiring.py:140` i
`seed_agent_001.py:180`. Živo je samo `CONTROLLED_LIVE` i `LIVE`
(`apps/policy/gateway.py:37`).

Puta da se to promeni nema:

| Gde sam tražio | Nalaz |
|---|---|
| komanda | nema nijedne |
| `PATCH /api/v1/personas/{id}` | polje **namerno izostavljeno** |

`api/serializers.py:128`, `PersonaPatchIn`: *„Samo polja bez sopstvenog toka
odobrenja."* Dozvoljeni su `display_name`, `disclosure_mode`,
`primary_locale`, `timezone`, `metadata`. Nepoznato polje serializer odbija
porukom „Ovo polje se ne menja kroz PATCH".

Dakle neko je ranije zaključio da prelazak u živo zaslužuje svoj postupak, pa
ga je zatvorio — a postupak nikad nije napisan. Zatvorena vrata bez vrata
pored njih.

## Odluka

**1. Jedan put, i to komanda:** `manage.py okruzenje`.

```
manage.py okruzenje --spisak
manage.py okruzenje --persona P-00012 --na CONTROLLED_LIVE \
                    --razlog "čita javne izvore za nalaze" --actor user:slobodan
```

**2. `--actor` i `--razlog` su obavezni, bez podrazumevane vrednosti.** Razlog
koji se podrazumeva nije razlog. Akter mora biti čovek (`user:…`) — agent ne
pušta ni sebe ni drugoga napolje.

**3. Upis u audit je svrha komande, ne njen propratni efekat.** Zapisuje se ko,
kada, kog agenta, iz čega u šta i zašto. Kad agenata bude deset hiljada,
pitanje „ko je ovog pustio napolje i sa kojim obrazloženjem" biće najčešće
pitanje koje ćemo postavljati; odgovor mora da postoji od prvog prelaska.

**4. U živo samo agent koji je READY ili ACTIVE.** Nacrt persone i povučena
persona nemaju šta napolju.

**5. Nazad u `SIMULATION` ide uvek i bez prepreke.** Stezanje ne sme nikad da
bude teže od popuštanja. Razlog se i tada upisuje, jer zapis služi i za povratak.

**6. Ista vrednost ne radi ništa i ne upisuje ništa.** Ponovljena komanda nije
događaj.

**7. `PersonaPatchIn` ostaje zatvoren.** Polje se i dalje ne menja kroz PATCH.
Put je jedan i vidi se.

## Šta se ovim NE menja

Okruženje samo po sebi **ne daje nijednu dozvolu**. Ono uklanja jedan od
uslova za živo izvršenje; poverenje, sposobnosti, odobrenja, kvote, prekidač
za gašenje i oba prekidača iz ADR-0099 važe nepromenjeno. Agent u
`CONTROLLED_LIVE` bez `code.write`, bez odobrenja i sa ugašenim prekidačem ne
radi ništa više nego pre.

`GLOBAL_EXTERNAL_ACTIONS_ENABLED` ostaje `false`.
