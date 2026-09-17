# MM Persona OS

Operativni sistem za digitalne persone, kao modul MercatoMaster ekosistema.
Jedan engine, proizvoljan broj persona koje dele infrastrukturu a razlikuju se
po identitetu, memoriji, ponašanju i kanalima.

**Faza: F0** — skelet. Nema modela, nema migracija, nema API-ja. Ovo je ono
što mora da stoji pre nego što se napiše prvi model.

## Izvor istine

| Dokument | Šta određuje |
|---|---|
| **Canon v1.1** | Imena, enum-e, opsege, ugovore. Normativno. |
| **Aneks A v1.0** | Šta je stvarno moguće po kanalu. Rok: 15.12.2026. |
| Ostalih 14 dokumenata | Formule, pragove, procedure, obrazloženja. |

Pravilo prvenstva kod konflikta: **Canon → kod u `main` → kasniji dokument →
raniji dokument**. Izmena Canon-a ide isključivo kroz ADR (`docs/adr/`), nikada
kroz uređivanje PDF-a.

## Šta F0 sadrži

```
common/enums.py       Ceo katalog enum-a (Canon §3). JEDINO mesto za enum.
common/ids.py         Dualni ID: UUID + public_id (Canon §2).
common/events.py      Event envelope i katalog 23 eventa (Canon §7).
apps/                 12 Django app-ova (Canon §1), prazni ali importabilni.
schemas/events/       23 JSON Schema, po jedna za svaki event.
policy/               capabilities.yaml, risk_weights.yaml.
channels/             identity_vehicles.yaml — dozvoljeni parovi kanal/oblik.
tools/canon_lint.py   Odbija ime van Canon-a. Ovo je ono što Canon drži živim.
tests/test_canon.py   82 testa kanonskih invarijanti.
docs/adr/             ADR-0001 (Canon v1.0), ADR-0002 (Aneks A → v1.1).
```

`common/` je namerno bez Django zavisnosti — isti modul koriste testovi,
workeri i lint alat.

## Pokretanje

```bash
cp .env.example .env
docker compose up -d postgres redis minio
pip install -e ".[dev]"

python tools/canon_lint.py     # mora proći
python -m pytest               # 82 testa
```

## Nekoliko odluka koje izgledaju sitno a nisu

**`ActionStatus` i `ExecutionOutcome` su dva enum-a.** Četiri dokumenta su
pokušala da jednim opišu i stanje akcije i ishod pokušaja — otuda četiri
nekompatibilna rečnika. `OUTCOME_TO_STATUS` je mapa prelaza.

**Rizik nije odluka.** `risk_score` (0–100, ceo broj) je svojstvo zahteva,
`PolicyEffect` je odluka, GREEN/YELLOW/RED je izvedena oznaka koja se nikada ne
upisuje. Akcija visokog rizika sa važećim odobrenjem je GREEN; akcija niskog
rizika pod kill-switch-om je RED.

**`UNKNOWN_EFFECT` nikada ne vodi u retry.** To je jedino stanje koje može
proizvesti duplikat spoljašnjeg efekta, a nulti duplikat je hard KPI pilota.
Ide u `runtime.reconcile` (task na queue-u `maintenance`).

**Playwright, bez stealth forkova.** Patchright je fork čija je svrha
prikrivanje automatizacije, što je u direktnoj koliziji sa `platform.evasion`
DENY pravilom koje sistem sam definiše. `CAPABILITY_UNAVAILABLE` je validan
ishod, ne greška.

**Trust L3 i L4 su rezervisani.** Podrazumevaju odlazni prvi kontakt, za koji
Aneks A nije našao sankcionisan put ni na jednoj platformi. Nivo koji stoji u
UI-ju a nema kanal na kom se izvršava navodi operatora da misli da postoji put
kojeg nema.

**LinkedIn samo kao Page.** Lični profil za AI personu je zabranjen i uz
otvoreno označavanje. `channels/identity_vehicles.yaml` to sprovodi kao
constraint, ne kao preporuku.

## Sledeće — F1

Šema i migracije `0001`–`0014`, seed `P-00001`. Canon §18.
