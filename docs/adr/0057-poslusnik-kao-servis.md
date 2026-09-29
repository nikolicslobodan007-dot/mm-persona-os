# ADR-0057 — Poslušnik kao servis, i radni primerak van `/tmp`

- **Status:** prihvaćen (29.09.2026.)
- **Prethodi:** ADR-0038 (poslušnik van aplikacije), ADR-0039, ADR-0048, ADR-0053, ADR-0033
- **Menja:** `mm-runner.service` — jedinica je postojala, ali bi u ovom obliku
  obarala svaki zadatak

## Šta se desilo

Poslušnik se od 25.09. pušta rukom. Dok je tako, departman za programiranje ne
može da radi bez čoveka za terminalom — a cilj je korporacija u kojoj agenti rade
umesto ljudi, ne devet agenata koji čekaju da im neko otvori vrata.

U beleškama je stajalo da instalaciju blokira `ProtectHome=true`, jer bi sakrio
`/home/mm/.ssh` koji poslušniku treba za `git push`. **To nije tačno**, i nije
bilo tačno kad sam to zapisao. `gurni()` gura u **lokalnu putanju**
(`git push /home/mm/apps/mm-persona-os HEAD:refs/heads/…`), a `trci()` ionako
pokreće svaki potproces sa `HOME=/tmp` i praznim okruženjem. Nikakav SSH ne
postoji. `README.md` pored samog fajla to kaže od 25.09.: *„Server ne gura nikuda
dalje i ne treba mu ključ sa pravom pisanja."*

Prava prepreka je bila druga, i ona je tiha.

## Prepreka koja bi prošla neopaženo

`PrivateTmp=true` daje servisu **svoj** `/tmp`. Radni primerak je nastajao sa
`tempfile.mkdtemp()`, dakle u tom privatnom `/tmp`, a onda se u kontejner ubacivao
ovako:

```yaml
volumes:
  - ${RADNI_PRIMERAK}:/rad
```

Bind montiranje ide **po putanji**. Poslušnik pošalje `/tmp/rad-xyz`; Docker demon
tu putanju razrešava u svom prostoru imena, gde je `/tmp` hostov, a `rad-xyz` ne
postoji. Demon bi napravio prazan direktorijum i montirao njega. `kapije.sh` nema,
sve četiri kapije padaju.

I onda ono najgore: **u zapisu bi stajalo da su kapije pale.** Po ADR-0053 to je
`AGENT` dok se ne dokaže drugo. Naš kvar u unit fajlu upisivao bi se kao agentov
promašaj, svaki put — tačno obrazac zbog kojeg postoje ADR-0048, 0049, 0050, 0051,
0052 i 0053.

## Odluka

### 1. Radni primerak ide u `/var/lib/mm-runner`

`StateDirectory=mm-runner` u jedinici, `PERSONA_WORKDIR=/var/lib/mm-runner` u
okruženju. `systemd` pravi direktorijum, daje ga servisu i uklapa ga sa
`ProtectSystem=strict`. Docker ga vidi isto jer je stvaran.

`PrivateTmp=true` **ostaje**. Sada je bezopasan — u `/tmp` ide samo poruka commita,
koju čita `git` u istom prostoru imena — a i dalje odvaja servis od tuđih
privremenih fajlova. Zaštita se ne skida zato što je jednom smetala; premešta se
ono što je bilo na pogrešnom mestu.

Pri ručnom puštanju `PERSONA_WORKDIR` nije postavljen i `/tmp` ostaje
podrazumevan, kao do sada.

### 2. Poslušnik proverava vidljivost pri startu, ne pretpostavlja je

`docker_vidi_isto()` napravi direktorijum sa markerom, montira ga read-only u
`mm-persona-os-web:latest` i traži marker unutra.

- vidi se → kreće;
- ne vidi se → **ne kreće**, vraća `3` i u dnevnik piše šta da se proveri;
- Docker se uopšte ne dobija → to je druga stvar, javi i nastavi (demon ume da
  kasni za servisom pri podizanju).

Razlika između „ne vidi se" i „nema Dockera" nije sitnica: prvo je podešavanje
koje bi tiho kvarilo svaki rezultat, drugo je stanje koje prođe samo od sebe.

`StartLimitBurst=3` u dva minuta: pogrešno podešen koren zaustavi servis umesto
da ga vrti u krug i jede red.

### 3. `/home` se krije, repozitorijum se vraća izričito

`ProtectHome=tmpfs` + `BindPaths=/home/mm/apps/mm-persona-os`. Ostatak `/home`
servis ne vidi — ni `~/.ssh` korisnika `mm`, a taj proces drži `docker.sock`.

Prvo je pisalo `ProtectHome=true` + `ReadWritePaths=`, uz moje „verujem da to
probija". **Ne probija.** Server je odgovorio odmah: `status=200/CHDIR`,
*„Changing to the requested working directory failed: Permission denied"*.
`ProtectHome` navuče prazan `tmpfs` preko `/home` i `ReadWritePaths=` tu ne
pomaže; `BindPaths=` izričito vrati jedan direktorijum unutra.

`ReadWritePaths=` ostaje pored `BindPaths=` — bind daje da se uđe, ovo da se
piše (poslušnik gura granu u taj repozitorijum).

### 4. Šta se namerno NIJE dodalo

`PrivateDevices=`, `RestrictNamespaces=`, uži `CapabilityBoundingSet=`. Svaka od
njih dodiruje ono što `docker` CLI radi sa demonom, i svaka bi tražila svoju
proveru. Kaljenje koje nije provereno nije kaljenje nego nada; dodaju se kad se
izmere, ne unapred.

## Šta je odbačeno

- **`ProtectHome=read-only` ili `ProtectHome=false`.** Rešava problem koji ne
  postoji (SSH ključ), a otvara ceo `/home` procesu koji ima `docker.sock`.
- **`RuntimeDirectory=` umesto `StateDirectory=`.** `/run` je u RAM-u. Na CX23 sa
  4 GB, uz Postgres, Redis, MinIO i pet kontejnera aplikacije, radni primerak i
  keš `pytest`-a u RAM-u su rizik bez razloga.
- **Radni primerak u samom repozitorijumu** (`/home/mm/apps/mm-persona-os/.rad/`).
  Vidljiv Dockeru, ali bi `git status` u produkcijskom stablu prikazivao tuđi rad,
  a `git clean` umeo da ga pojede usred zadatka.
- **Popravka bez provere pri startu.** Prvo sam hteo samo da premestim
  direktorijum. Tada bi sledeće pogrešno podešavanje iste vrste opet ispalo kao
  agentova greška — a ceo ovaj ADR postoji zbog te vrste.

## Kako je provereno

29.09.2026. na `mm-persona-os-01`:

1. **Prva instalacija je pala** — `status=200/CHDIR`, trinaest pokušaja ponovnog
   pokretanja u tri minuta dok `StartLimitBurst` nije stao. Uzrok:
   `ProtectHome=true`. To je upisano u odluku iznad.
2. Sa `ProtectHome=tmpfs` + `BindPaths=`: `active (running)`, i u dnevniku
   `poslušnik kreće; repo: /home/mm/apps/mm-persona-os | radni koren:
   /var/lib/mm-runner`.
3. **Proba vidljivosti je prošla** — `/var/lib/mm-runner` Docker vidi isto.
   Posle ovog ADR-a i uspeh se upisuje u dnevnik: ćutanje bi značilo i „prošlo
   je" i „nije se ni probalo", a razlika je upravo ono zbog čega provera postoji.
4. Pun zadatak kroz servis — od reda do grane. Ishod ide u `stanje-rada.md` kad
   prvi zadatak prođe.

## Posledice

- `deploy/runner/mm-runner.service` — `StateDirectory`, `PERSONA_WORKDIR`,
  granice ponovnog pokretanja, tri dodate zaštite koje ne diraju Docker.
- `deploy/runner/runner.py` — `RADNI_KOREN`, `docker_vidi_isto()`, `pospremi()`,
  provere pri startu.
- `deploy/runner/README.md` — odeljak zašto radni primerak ne sme u `/tmp`.
- Bez migracije, bez izmene aplikacije.
- 7 novih provera; ukupno **1071**. One pokrivaju **odluku** (šta poslušnik radi
  kad koren nije vidljiv, kad Dockera nema, kad slike nema), ne i samo okruženje —
  ono se proverava puštanjem (README, poslednji odeljak).

## Zapisano za ADR-0033

Dva puta ista greška, u istom danu.

**Prvo:** u belešku „sledeći korak" upisao sam uzrok — SSH ključ — koji nikad
nisam proverio, a `README.md` u istom direktorijumu ga demantuje. Jutros sam ga
ponovio Slobodanu kao činjenicu i predložio ADR o njemu. Da nisam otvorio
`runner.py`, napisali bismo odluku o problemu koji ne postoji.

**Drugo:** pravi kvar — `PrivateTmp=` naspram bind montiranja — nije se video ni
u jednom fajlu koji sam pročitao. Našao sam ga tek kad sam pitao *šta ovaj proces
zaista predaje Dockeru*, umesto *šta mu treba sa diska*.

Pravilo: **beleška o uzroku nije nalaz.** Ono što je zapisano kao „zapelo je na
X" proverava se u kodu pre nego što postane ADR — i onda kad je zapisano mojom
rukom. Naročito onda.
