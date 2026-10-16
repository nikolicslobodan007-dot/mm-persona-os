# ADR-0099 — Čitanje javnog weba nije delovanje

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Agent ne može da pročita nijednu javnu stranicu dok se ne otvori i
  objavljivanje, slanje pošte i sve ostalo. Jedan prekidač za dve različite
  stvari.
- **Prethodi:** ADR-0008, ADR-0017, Canon §6.4, §12.1, §12.6, Aneks A §5
- **Menja:** `config/settings/base.py`, `apps/policy/gateway.py`,
  `apps/runtime/transport.py`. Testovi uz to.
- **Canon:** §6.4, §12.6

## Izmereno

Kako prekidač danas radi, pročitano u kodu 16.10.:

| Mesto | Šta radi |
|---|---|
| `apps/policy/gateway.py:56` | `external_live()` = globalni prekidač **i** persona u živom okruženju |
| `apps/runtime/executor.py:145` | `DryRunTransport()` ako nije živo, inače `LiveTransport()` |
| `apps/runtime/transport.py:129` | `_guard()` — **druga, nezavisna** provera istog prekidača u `LiveTransport` |
| `apps/policy/gateway.py:108-112` | prekidač za gašenje se proverava **pre** svega toga |

Dva nalaza koja ovu odluku čine mogućom:

**1. Podela na čitanje i pisanje već postoji u rečniku sistema.**

```python
READ_ACTION_TYPES: frozenset[str] = frozenset({"browser.page.read", "channel.read.public"})
```

`common/enums.py:1372`. Danas se koristi samo na jednom mestu —
`executor.py:58`, da čitanje dobije tri pokušaja a pisanje dva. Podelu ne
izmišljamo, samo je uzimamo ozbiljnije.

**2. `Request` već nosi oblik zahteva, i podrazumevano je zatvoren.**

```python
write: bool = True   # da li zahtev menja stanje na drugoj strani
```

`transport.py:60`. Podrazumevano **True**: ko zaboravi da označi zahtev kao
čitanje, ostaje na strani pisanja. Adapter za web izričito šalje `write=False`
uz `GET`.

**3. Čitanje je već napisano pošteno.** `apps/runtime/adapters/web.py`:
istinit User-Agent sa kontaktom (nikad lažni Chrome), `robots.txt` se poštuje
uključujući `Crawl-delay`, najviše jedan zahtev u sekundi po domaćinu. Model
traži `robots_respected` (Canon §12.6).

## Odluka

**1. Dva prekidača umesto jednog.** `GLOBAL_EXTERNAL_ACTIONS_ENABLED` ostaje
netaknut i i dalje znači ono što je značio: ništa ne izlazi napolje. Pored
njega stoji `GLOBAL_PUBLIC_READS_ENABLED`, podrazumevano `false`.

**2. Novi prekidač otvara isključivo čitanje.** Zahtev ide živo samo ako važi
**sve** od ovoga:

- `action_type` je u `READ_ACTION_TYPES`;
- `GLOBAL_PUBLIC_READS_ENABLED` je tačno;
- persona je u živom okruženju (uslov se ne menja);
- odluka politike je ALLOW i nijedan prekidač za gašenje nije u opsegu
  (proverava se ranije i ostaje netaknuto).

Piše se kao **I**, nikad kao **ILI** uz postojeći uslov. „Ili" bi pustilo da
novi prekidač otvori nešto što nije čitanje, a to je tačno ono što ova odluka
treba da spreči.

**3. Druga brava ne veruje prvoj na reč.** `LiveTransport` i dalje proverava
nezavisno, ali kad je veliki prekidač ugašen a mali upaljen, on ne gleda
nalepnicu nego **oblik zahteva**: prolazi samo `write=False`, metod `GET`, bez
`json`, bez `form`, bez `body` i bez `auth`. Tajna se u takvom zahtevu ne čita
jer je nema čemu da se doda.

Razlog: nezavisna provera koja veruje polju koje je postavio pozivalac nije
nezavisna. Oblik zahteva transport vidi sam.

**4. Prekidač za gašenje pobeđuje i ovde.** Ne zato što dodajemo proveru, nego
zato što se on proverava pre nego što se o živom izvršenju uopšte odlučuje.
Izmereno, ne pretpostavljeno.

**5. `READ_ACTION_TYPES` od danas nosi težinu.** Do sada je taj skup odlučivao
samo broj pokušaja i dodati nešto u njega bilo je bezopasno. Posle ove odluke
on odlučuje **šta sme napolje dok je veliki prekidač ugašen**. Zato: dodavanje
u taj skup je od sada odluka koja ide kroz ADR, kao i svaka druga promena
granice.

Ovo je glavna nova opasnost koju ova odluka uvodi i zato stoji napisana. Neko
bi za godinu dana dodao `channel.dm.read` da dobije tri pokušaja i time, ne
znajući, otvorio živi put napolje.

**6. Čitanje ostaje pošteno.** Pravila iz `web.py` se ne diraju: istinit
User-Agent, `robots.txt`, jedan zahtev u sekundi. Prekidač ne daje pravo da se
bilo šta zaobiđe. Stranica koja nas ne želi i dalje nas nema.

**7. Upaljen mali prekidač se vidi.** Dok je upaljen, u evidenciji svakog
živog čitanja stoji da je nastalo pod njim, a ne pod velikim. Čovek mora da
može da pita „šta je izašlo napolje dok je veliki prekidač bio ugašen" i da
dobije spisak.

## Šta se ovim NE menja

Objavljivanje, slanje pošte, lajk, komentar, poruka — sve stoji do GO odluke.
Nijedan od tih tipova nije u `READ_ACTION_TYPES` i ovaj prekidač ih ne dodiruje.

Persona u SIMULATION ili SHADOW okruženju i dalje ne radi ništa napolju, ni
čitanje. Delegiranje i dalje ne daje nijednu dozvolu (ADR-0017).

Odobrenja, kvote, politika i evidencija rade kao do sada. Ovo nije zaobilaženje
jednog koraka nego sužavanje jednog prekidača.

`GLOBAL_EXTERNAL_ACTIONS_ENABLED` ostaje `false`. Ova odluka ga ne pali i ne
približava paljenju; ona uklanja razlog zbog kog bi se palio prerano.
