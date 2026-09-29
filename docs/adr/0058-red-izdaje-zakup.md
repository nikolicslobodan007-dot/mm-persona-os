# ADR-0058 — Red izdaje zakup, ne poziv

- **Status:** prihvaćen (29.09.2026.)
- **Prethodi:** ADR-0040 (red drži nemeren posao), ADR-0038, ADR-0048, ADR-0053, ADR-0057, ADR-0033
- **Menja:** ADR-0040 — `/tasks/queued` više nije isti spisak za svakoga ko pita

## Šta se desilo

Prvi zadatak koji je prošao kroz poslušnik-kao-servis (ADR-0057) vratio je ovo:

```
kapije: {'pytest': False, 'ruff': True, 'canon_lint': True, 'migrations': True}
```

a komanda je za isti zadatak prikazala **`canon_lint — pala`**. Jedan od ta dva
je lagao.

U bazi je bilo **osam redova umesto četiri**, po dva za svaku kapiju:

| kapija | red sa ispisom | red bez ispisa |
|---|---|---|
| pytest | `False`, 3597 znakova | `False`, 0 |
| ruff | `True`, 18 | `False`, 0 |
| canon_lint | `True`, 161 | `False`, 0 |
| migrations | `True`, 19 | `False`, 0 |

Parovi su razmaknuti pola milisekunde, a poredak unutar para je naizmeničan.
Zapis je pokazao **osam različitih `trace_id`** — osam odvojenih zahteva, svi
`service:runner`. `pgrep` je pokazao zašto:

```
332905   /usr/bin/python3 /home/mm/apps/.../runner.py   ← servis
3774416  python3 deploy/runner/runner.py                 ← ručni, zaostao
```

Dva poslušnika. Obojica su pitala `/tasks/queued`, obojica dobila isti zadatak,
obojica ga odradila i upisala kapije.

Zašto je jedan skup bio prazan: `COMPOSE_PROJECT_NAME` se izvodio **samo iz
zadatka**, pa su oba prolaza dizala iste kontejnere. Jedan je radio `up`, drugi
mu je u isto vreme uradio `down -v --remove-orphans`. Kontejneri su pobijeni
usred rada, `kapije.sh` nije ostavio ni `.log` ni `.status`, i `kapije()` je sve
pročitao kao `False`.

A `gate_report` uzima **poslednji red po vremenu upisa**. Danas je to oborilo
`canon_lint`; sutra bi bilo koju.

To je opet isti obrazac: **naš kvar upisan kao agentov promašaj** (ADR-0048,
0049, 0050, 0051, 0052, 0053). Po ADR-0053 pala kapija je `AGENT` dok se ne
dokaže drugo.

## Odluka

### 1. Zadatak se preuzima, sa rokom

`CodeTask.claimed_by` i `CodeTask.claimed_until`. `POST /tasks/{id}/claim`
preuzima, `POST /tasks/{id}/release` vraća.

Preuzimanje ide pod `select_for_update`. To nije ukras: dva poslušnika koja
pitaju u istoj milisekundi moraju da se poređaju, inače bi obojica pročitala
„slobodan" — isti kvar, samo jedan sloj niže.

Zakup traje **30 minuta**, duže od najdužeg prolaza kapija (poslušnik ima rok od
900 s) plus kloniranje i commit. Istekao zakup je slobodan zadatak: poslušnik
koji padne ne zaključava posao zauvek.

**Isti poslušnik sme da preuzme ono što već drži.** Bez toga bi servis posle
ponovnog pokretanja čekao pola sata na sopstveni zakup.

### 2. Ishod sme da upiše samo držalac zakupa

`/gate`, `/result` i `/unapplied` traže `X-Runner-ID` i živ zakup na to ime.

Ovo je **dozvola, ne heuristika.** Mogao sam da napišem pravilo „red sa ispisom
pobeđuje red bez ispisa" i brojevi bi se danas složili. Ali to je pogađanje ko
je u pravu; ovo je pitanje ko je uopšte imao pravo da upiše — isti duh kao
ADR-0034.

`X-Actor-ID` kaže **ulogu** (`service:runner`), a zakup je o **primerku**. Zato
posebno zaglavlje.

**Čovek je izuzet.** Zakup rešava trku između mašina; operater koji upisuje ishod
rukom ne trči ni sa kim, a njegov potez ionako nosi ime u zapisu (ADR-0045).
Tražiti zakup od čoveka zatvorilo bi jedini put kojim se zaglavljen zadatak
razrešava.

### 3. Red ne nudi ono što je pod tuđim živim zakupom

Svoj zakup **ostaje** u redu — poslušnik posle pada mora da vidi ono što je sam
započeo.

### 4. Ime compose projekta nosi slučajan sufiks

`zad-<tsk>-<6 hex>`. Dva prolaza istog zadatka nikad ne dele kontejnere. Ovo bi
trebalo i bez zakupa: ponovni pokušaj istog zadatka posle isteka zakupa gađao bi
isto ime.

### 5. Poslušnik ima ime

`PERSONA_RUNNER_ID`, u jedinici postavljeno na `mm-runner` — stabilno, pa servis
posle restarta nastavlja svoj posao. Ručno pokretanje nema tu promenljivu i
dobija `host:pid`, pa **ne može da preotme servisov zadatak.** Da je ovo
postojalo jutros, zaostali proces bi bio bezopasan.

## Šta je odbačeno

- **„Red sa ispisom pobeđuje."** Rešava simptom i ostavlja dva poslušnika da rade
  isti posao — dvostruki trošak procesora i dva commita na istoj grani.
- **Jedan poslušnik zauvek**, sprovedeno bravom na fajlu. Jeftino danas, a
  zatvara skaliranje koje je ceo cilj: 10.000 agenata ne opslužuje jedan proces.
- **Nov član u `ErrorCode`** za sudar zakupa. `common/enums.py` je zaštićena zona
  (ADR-0034 §5.1), a Canon §8.5 je rečnik grešaka za sve klijente. Sudar zakupa
  ide kao `VERSION_CONFLICT`, što je već 409 — ono što poslušnik proverava. Ako
  se ikad bude trebalo razlikovati, to je svoj ADR.
- **Zakup u Redisu** umesto u bazi. Redis bi bio brži i pogrešan: zakup je deo
  stanja zadatka i mora da preživi restart Redisa kao i sve ostalo.
- **Produžavanje zakupa u toku posla** (heartbeat). Trideset minuta pokriva
  najduži poznat prolaz sa rezervom. Kad prolaz bude duži od toga, to je merenje
  koje tek treba da se desi.

## Posledice

- `CodeTask.claimed_by`, `CodeTask.claimed_until` (**migracija
  `0011_zakup_zadatka`**), `zadaci.claim/release/drzi_zakup/zakup_zivi`,
  `TaskClaimView`, `TaskReleaseView`, straža na tri tačke, filter u redu.
- `deploy/runner/runner.py` — ime poslušnika, `X-Runner-ID`, preuzimanje pre
  posla i vraćanje u `finally`, slučajan sufiks u imenu compose projekta.
- `deploy/runner/mm-runner.service` — `PERSONA_RUNNER_ID=mm-runner`.
- Ugovor `contracts/openapi/persona-os-v1.yaml` regenerisan (dve nove tačke).
- 12 novih provera; ukupno **1083**.
- **Zatečeni redovi se ne diraju.** Osam redova nad TSK-…35ED8QY ostaje kakvo
  jeste; zapis se ne doteruje da bi brojevi izgledali bolje (ADR-0046). Taj
  zadatak se meri ponovo, novom zakrpom.

## Zapisano za ADR-0033

Tri stvari.

**Prva:** ovo se nije videlo dok je poslušnik bio jedan. Rupa je postojala od
25.09. i ćutala je, jer je uslov za nju — dva poslušnika — nastao tek danas, i to
slučajno, zaostalim procesom. **Pravilo koje pretpostavlja da postoji samo jedan
od nečega otkazuje onog dana kad ih bude dva, a taj dan ne najavljuje sebe.**

**Druga:** prvo objašnjenje koje mi je palo na pamet bilo je „API upisuje dvaput".
Pročitao sam pogled, serijalizator i `record_gate` — sve ispravno — i tek onda
pitao **podatke** umesto koda. Osam `trace_id`-jeva je odgovorilo za sekund ono
što pola sata čitanja koda nije.

**Treća:** zamalo sam napisao „red sa ispisom pobeđuje". Radilo bi, danas. Kad
popravka čini da se brojevi slože, treba pitati da li je popravljen uzrok ili je
samo merilo naučeno da gleda na drugu stranu.
