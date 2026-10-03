# ADR-0073 — Brif nosi i ono što se čita, po zadatku

- **Status:** prihvaćen (03.10.2026.)
- **Prethodi:** ADR-0041 (brif), ADR-0061 (referenca i zaštićene zone),
  ADR-0034 §5.1 (opseg pisanja), ADR-0044 §3 (`NE MOGU` je ispravan ishod),
  ADR-0060 (priručnik radnog mesta), ADR-0033 (pravilo nula)
- **Menja:** `CodeTask.reference_paths` (migracija 0012), `brif._referenca`,
  `zadaci.create` i `zadaci.set_reference`, `manage.py zadatak --referenca`
- **Canon:** §6.4, §20

## Šta se desilo

03.10.2026. Pavol Hudák (P-00029) je dobio prvi zadatak — strana „Grane" u
konzoli. Zadatak mu je izričito rekao odakle podaci: `rezultat.za_pregled()`,
bez novog računanja, jer ta funkcija postoji i ima svoje provere (ADR-0071).

Vratio je:

> `NE MOGU: zadatak traži podatke iz rezultat.za_pregled() … ali u priloženim
> fajlovima ne postoji nijedan model, servis ili objekat koji nudi`

**Bio je u pravu.** Brif nosi dve grupe fajlova: ono što zadatak sme da dira
(`allowed_paths` — ovde `console`) i **fiksnu** referencu, do danas zakucanu u
kod:

| `brif.REFERENCA` | zašto je tu |
|---|---|
| `common/enums.py` | rečnik — član enuma se ne izmišlja (ADR-0061) |
| `apps/observability/models.py` | polja audit zapisa (ADR-0068) |
| `api/audit.py` | kako se zapisuje |

`apps/orchestration/rezultat.py` nije ni u jednoj od te dve grupe. Tražili smo
od agenta da se spoji sa kodom **koji mu nismo pokazali**, a onda bi — da nije
poštovao pravilo 8 — izmislio potpis funkcije i pao na kapijama.

Ovo nije Pavolov kvar nego naš, i nije jednokratan: **svaki zadatak koji dodiruje
postojeći kod van svog opsega pisanja udara u isti zid.** Strana konzole koja
čita servis, kanal koji zove politiku, šablon koji prikazuje model — svi.

## Odluka

### 1. Spisak za čitanje postaje polje zadatka

`CodeTask.reference_paths` — pune putanje do fajlova (ne prefiksi), uz onu
globalnu trojku koju nosi svaki brif. Prazno znači „samo globalna referenca",
kao do sada, pa se nijedan postojeći zadatak ne menja.

```
manage.py zadatak --zadatak TSK-… --referenca apps/orchestration/rezultat.py
```

### 2. Čitanje i pisanje su dve različite stvari

Fajl na ovom spisku **ne postaje** fajl koji se sme menjati. `may_touch` i
poverenje po opsegu (ADR-0034) rade isto što i pre, i provera
`test_citanje_ne_daje_pravo_pisanja` pada ako se to ikad promeni. Zato zaštićena
zona ovde **sme** da se nađe: pravilo 7 priručnika kaže da se zona čita, ne
menja, a to je bilo tačno i pre ovog ADR-a — samo se spisak nije mogao proširiti.

### 3. Isti plafon, isto sečenje

Referenca po zadatku ulazi u `MAX_TOTAL_BYTES` kao i sve ostalo i, za `.py`,
kroz isti izvod (zaglavlja klasa i imena, ADR-0068). Ono što ne stane ide u
`truncated`, vidljivo. Budžet koji ima izuzetak nije budžet (ADR-0041 §1).

### 4. Globalna trojka ostaje globalna

Nije rešenje dodati `rezultat.py` u `REFERENCA`. Tada bi svaki zadatak u firmi
nosio tuđi fajl, plafon bi se trošio na ono što tom zadatku ne treba, i spisak
bi rastao dok ga niko ne bi smeo dirati. Globalno ostaje ono što treba **svima**.

## Šta je odbačeno

- **Dati piscu alat „pročitaj fajl kad ti zatreba".** Zvuči opštije i jeste, ali
  svaki poziv je još jedan prolaz kroz model i još jedan trošak po pokušaju, a
  zadatak ionako unapred zna sa čim se spaja. Ostaje otvoreno za slučaj kad se
  ne zna unapred.
- **Priložiti ceo `apps/orchestration`.** Opseg čitanja koji je širok koliko i
  repozitorijum nije opseg, i plafon bi pojeo ono zbog čega je zadatak otvoren.
- **Pustiti agenta da pogađa potpis funkcije.** To bi bilo tiho preokretanje
  pravila 8 u „pogađaj pa neka kapije presude".

## Posledice

- `apps/orchestration/models.py` → `CodeTask.reference_paths`; migracija
  `0012_referenca_po_zadatku`.
- `apps/orchestration/zadaci.py` → `create(reference_paths=…)`,
  `set_reference`; audit `task.reference_changed`.
- `apps/orchestration/brif.py` → `_referenca(koren, zadatak)`.
- `apps/orchestration/management/commands/zadatak.py` → `--referenca`
  (`-` briše spisak); `cita:` u ispisu stanja.
- `tests/test_brif.py` → `TestReferencaPoZadatku`, 8 provera.

## Zapisano za ADR-0033

Zadatak sam napisao ja, i u njemu sam **imenovao funkciju** koju agent treba da
pozove — a nisam proverio da li je može videti. Ista greška kao ADR-0065, samo
na drugom kraju: tamo sam agentu dao pravilo koje nisam proverio nad alatom,
ovde zadatak koji nisam proverio nad brifom.

Mera koja je nedostajala je jedno pitanje pre otvaranja zadatka: **sve što sam
imenovao — je li u brifu?** Od danas je to deo otvaranja zadatka, ne dobra volja.

Drugo, i vrednije: **ovo je prvi put da je agent odbio da pogađa.** Pravilo 8
stoji u priručniku od 01.10. i do danas se nije videlo na delu. Umesto zakrpe
koja izgleda tačno dok ne padne na kapijama, dobili smo rečenicu koja tačno kaže
šta fali — za 12 centi i jedan pokušaj od osam. Toliko vredi pravilo koje je
agent zaista poslušao.
