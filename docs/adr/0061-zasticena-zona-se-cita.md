# ADR-0061 — Zaštićena zona se ne dira, ali se čita

- **Status:** prihvaćen (30.09.2026.)
- **Prethodi:** ADR-0041 (brif), ADR-0034 §5.1 (zaštićene zone), ADR-0033 (pravilo
  nula), ADR-0050 i ADR-0051 (ishod mora da stigne do modela), ADR-0053
- **Menja:** ADR-0041 — brif više ne daje samo fajlove pod dozvoljenim putanjama
- **Canon:** §6.4 (izvršni ugovor), §20 (enumi), §9.5 (poverenje)

## Šta se desilo

30.09. u 09:02, drugi pokušaj P-00027 na `TSK-01M3Q5GV73QRFVXWAYHSNDCXKJ`. Model
**nije vratio zakrpu.** Vratio je objašnjenje:

> „Proveravam `E.StepStatus` — koristim `SKIPPED` koji već postoji u kodu ranijih
> verzija (`E.StepStatus.DONE` se koristi), pretpostavljam da `SKIPPED` postoji u
> `common/enums.py` jer ga zaštićena zona sadrži, **ali ne mogu da je gledam**."

Zaustavio se jer bi morao da pretpostavi. **To je tačno ono što mu naše prvo
pravilo nalaže** (ADR-0033), a naš brif mu je onemogućio da ga ispuni. Cena: 9
centi i pokušaj 2 od 3.

Izmereno u `apps/orchestration/brif.py`:

```python
if zona := policy.path_is_protected(rel):
    odsečeno.append({"path": rel, "reason": f"zaštićena zona ({zona})"})
    continue
```

Brif daje **spisak** zaštićenih putanja — da agent zna šta ne sme da dira — i
**sadržaj nijedne**. Uz to `_kandidati()` ne izlazi van `allowed_paths`, pa
`common/enums.py` nikad nije ni bio kandidat.

A `policy/capabilities.yaml` kaže:

```
code.read:
  description: "Čitanje izvornog koda korporacije"
  min_trust_level: L0
```

**Politika mu dozvoljava da čita. Brif to nije radio.** Pobrkali smo dve stvari i
od pravila o pisanju napravili slepilo.

Dosad je prolazilo samo zato što su svi raniji zadaci bili u `apps/content`, gde
se enumi ne pominju. Rupa je postojala od ADR-0041 i čekala prvi zadatak koji
imenuje status.

## Odluka

### 1. Zaštićena zona zabranjuje izmenu, ne čitanje

Dve različite stvari koje su do danas delile jedan spisak:

| | ko odlučuje | šta znači |
|---|---|---|
| `protected_paths` | ADR (ADR-0034 §5.1) | **ne sme da se menja**, ni na jednom nivou poverenja |
| `code.read` | poverenje (L0, svima) | **sme da se čita** |

Agent koji sme da menja ono što ga ograničava nije ograničen — to ostaje. Ali
agent koji ne sme ni da vidi pravila po kojima radi nije ograničen nego **slep**,
a slep agent pogađa. Pogađanje je tačno ono što ADR-0033 zabranjuje.

### 2. Brif dobija odeljak `reference`

Fajlovi koje pisac sme da čita a ne sme da menja, označeni `read_only: true`. U
promptu stoje pod zaglavljem koje to kaže izričito:

```
REČNIK — SMEŠ DA GA ČITAŠ, NE SMEŠ DA GA MENJAŠ.
Ako ti treba član enuma ili šifra, ovde piše koji postoje.
Nemoj da pretpostavljaš; ako ga ovde nema, kaži to.
```

Zaglavlje nije ukras. Bez njega bi model fajl koji vidi razumno smatrao fajlom
koji sme da menja, i sledeći kvar bi bila zakrpa nad `common/enums.py`.

**Provereno u sloju koji dela**, ne samo u onom koji je zgodan: izmena je i u
`brif.build` i u `pisac._prompt`. ADR-0050 je napisan zato što je jednom bila
samo u prvom.

### 3. U referenci je `common/enums.py`, i zasad samo on

`common/enums.py` je rečnik celog sistema (Canon §20). Svaka zakrpa koja imenuje
status, ishod ili šifru greške mora da vidi koji članovi postoje. Spisak se širi
ADR-om, ne osećajem: svaki nov fajl u referenci troši budžet koji je nekom drugom
potreban.

### 4. Ide izvod, ne ceo fajl

Pisac traži **rečnik, ne prozu**. Izvod su zaglavlja klasa i članovi u velikim
slovima; dokumentacija i tela metoda ostaju napolju.

| | bajtova | od `MAX_TOTAL_BYTES` (200 kB) |
|---|---|---|
| ceo `common/enums.py` | 41.552 | 20,8 % |
| **izvod** (510 redova) | **15.874** | **7,9 %** |

Izvod sadrži `SKIPPED` — dakle tačno ono što je 30.09. nedostajalo, u osmini
plafona.

### 5. Referenca ulazi u isti plafon

Ne „pored" budžeta. Budžet koji ima izuzetak nije budžet nego predlog, i rastao
bi dok neko ne primeti. Ono što ne stane ide u `truncated` sa razlogom, kao i
svaki drugi fajl (ADR-0036 §1 — tiho ispuštenih stvari nema).

## Šta je odbačeno

- **Dodati `common/enums.py` u `allowed_paths` zadatka.** Rešilo bi čitanje i
  otvorilo pisanje. Zaštićena zona bi ga i dalje odbila pri primeni, ali bi model
  dobio poruku da tamo sme — i trošio bi pokušaje na zakrpe koje ne mogu proći.
- **Izuzeti referencu iz plafona.** Vidi §5.
- **Slati ceo fajl.** Tri četvrtine su dokumentacija koja ne odgovara na pitanje
  zbog kog je ADR napisan, a zauzela bi petinu budžeta.
- **Pustiti agenta da traži fajl kad mu zatreba** (alat „pročitaj fajl"). To je
  drugi sistem — krug razgovora umesto jednog poziva — i svoja odluka sa svojim
  troškom. Danas je poziv jedan (ADR-0044) i to ostaje.
- **Reći mu u promptu „`SKIPPED` postoji, veruj mi".** To je pretpostavka
  preseljena sa agenta na nas, i istog dana kad se enum promeni postaje laž.

## Posledice

- `brif.build` → nov ključ `reference`; `REFERENCA`, `_referenca()`,
  `_izvod_enuma()`.
- `pisac._prompt` → nov odeljak sa izričitom oznakom „samo za čitanje".
- 4 nove provere; ukupno **1095**.
- Zatečena zakrpa `01deeb1d` je pripisana `SISTEM` (ADR-0053) — model nije
  pogrešio nego je odbio da pogađa.
- **P-00027 ima još jedan pokušaj od tri** na ovom zadatku. Ne troši se dok brif
  ne bude ispravljen na serveru.

## Zapisano za ADR-0033

**Prva:** naučili smo agenta pravilu „ne pretpostavljaj", a onda ga stavili u
položaj u kom se to pravilo ne može ispuniti. **Pravilo koje se ne može ispuniti
ne proizvodi poslušnost nego zastoj** — i to skup zastoj, jer se plaća po
pokušaju. Kad agent stane umesto da pogodi, prvo pitanje nije šta je s njim nego
šta smo mu uskratili.

**Druga:** ovo se ne bi videlo na zadacima u `apps/content`, gde enumi ne trebaju.
Videlo se prvog dana kad je zadatak dodirnuo status. **Rupa koja čeka određenu
vrstu zadatka izgleda kao da ne postoji sve dok taj zadatak ne dođe** — isto kao
ADR-0058, gde je uslov bio drugi poslušnik.

**Treća:** poruka o grešci je bila potpuna i tačna. Model je napisao šta mu treba,
zašto ne može, i stao. Da je vratio nasumičnu zakrpu, tražili bismo uzrok u
kapijama. **Agent koji ume da kaže šta mu fali vredi više od agenta koji uvek
nešto vrati** — i to treba da stoji u priručniku kad ga budemo pisali (ADR-0060).
