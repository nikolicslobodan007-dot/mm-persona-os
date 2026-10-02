# ADR-0068 — Referenca u brifu nosi i model, ne samo rečnik

- **Status:** prihvaćen (02.10.2026.)
- **Prethodi:** ADR-0061 (zaštićena zona se čita), ADR-0044 §3 (`NE MOGU` je
  ispravan ishod), ADR-0033 (pravilo nula), ADR-0060 (priručnik, pravilo 8)
- **Menja:** `brif.REFERENCA` i pravilo izvoda; ADR-0061 ostaje na snazi, ovo mu
  popunjava mesto koje je ostavio praznim
- **Canon:** §6.4, §20

## Šta se desilo

ADR-0061 je 30.09. nastao iz zastoja: P-00027 nije mogao da potvrdi da
`E.StepStatus.SKIPPED` postoji, pa je umesto zakrpe vratio objašnjenje. Popravka
je bila odeljak `reference` u brifu — fajlovi koje pisac sme da čita a ne sme da
menja. U njemu je ostao **jedan** fajl: `common/enums.py`.

02.10. je isti zastoj došao drugi put, iz drugog fajla. Zadatak je tražio proveru
nad `AuditEvent`. Model nije ni u dozvoljenim putanjama ni u referenci, pa je
pisac:

| pokušaj | šta je uradio | ishod |
|---|---|---|
| 2 | **pogodio** ime polja: `ev.details_json` | `pytest` pao, `AttributeError` |
| 3 | vratio `NE MOGU: treba mi model AuditEvent` | `REJECTED`, ispravno po pravilu 8 |

Između ta dva pokušaja recenzent mu je u nalazu **dao tačan put** (`payload`, pa
`details`, pa `message`). Pisac ga nije upotrebio: činjenicu o fajlu koji ne vidi
tretirao je kao pretpostavku. To je dosledno pravilu 8 i tako se i knjiži — ali
pokazuje da se rupa ne krpi porukom, nego referencom.

## Odluka

### 1. Referenca dobija model i funkciju koja ga puni

```
REFERENCA = ("common/enums.py", "apps/observability/models.py", "api/audit.py")
```

Model sâm kaže da polje `payload` postoji, ali **ne** i da `audit.record` u njega
upisuje ključ `details`. Bez `api/audit.py` pisac i dalje pogađa unutrašnji
ključ, pa su oba ili nijedno.

### 2. Izvod hvata svako ime koje klasa definiše, ne samo VELIKA

`_CLAN` je bio `^    [A-Z][A-Z0-9_]* = ` — pisan za enume. Polja Django modela su
mala slovima, pa bi izvod novog fajla bio 204 bajta **bez ijednog polja**.
Dodati fajl na spisak bez ove izmene ne bi rešilo ništa.

Izmereno 02.10.2026, nad pravim fajlovima:

| fajl | ceo | staro pravilo | **opšte pravilo** |
|---|---|---|---|
| `common/enums.py` | 41.552 B | 15.874 B | **15.874 B — bajt u bajt isto** |
| `apps/observability/models.py` | 11.699 B | 204 B (beskorisno) | **3.426 B (1,7 %)** |
| `api/audit.py` | 3.006 B | ceo (nema klasa) | 3.006 B (1,5 %) |

Rečnik se ne menja ni za jedan bajt; ukupan trošak reference raste za 6.432 B,
odnosno **3,2 % plafona brifa**. Fajl bez ijedne klase vraća se ceo — to je
zatečeno ponašanje i ostaje.

Za pisca su član enuma i polje modela ista vrsta činjenice: **ime koje sme da
napiše a ne sme da izmisli.** Pravilo koje ih razdvaja po veličini slova razdvaja
ih po slučajnosti.

### 3. Referenca i dalje ulazi u isti plafon

Ništa se ne menja u ADR-0061 §: što ne stane ide u `truncated` sa razlogom.
Postojeća provera to i dalje meri.

## Šta je odbačeno

- **Dati pisca alat „pročitaj fajl kad ti zatreba".** Ostaje otvoreno pitanje sa
  svojim ADR-om (ADR-0062 mu je uklonio argument troška). Dok ga nema, referenca
  je mesto gde se činjenica daje unapred.
- **Rešiti ovo nalazom, kako smo probali danas.** Probano i **nije radilo**:
  pisac je odbio činjenicu koju ne može da proveri nad fajlom, i bio je u pravu.
  Nalaz je kanal za sud o radu, ne za rečnik.
- **Staviti ceo `apps/observability/models.py`.** 11.699 B naspram 3.426 B za
  isti odgovor; proza i `Meta` klase ne kažu koja polja postoje.
- **Praviti spisak reference po zadatku.** Primamljivo i verovatno tačno, ali to
  je nova mehanika sa svojim merenjem; danas je dovoljan opšti spisak koji je
  i dalje ispod 10 % plafona.

## Posledice

- `apps/orchestration/brif.py` → `REFERENCA` (tri fajla), `_izvod_enuma`
  preimenovan u `_izvod` sa opštim `_CLAN`.
- `tests/test_brif.py` → 6 novih provera; ukupno **1170**.
- `TSK-01M3Y4Q9H1WK9M9WN7J5HZEDZE` — pokušaji 2 i 3 (11 centi) idu `SISTEM`-u
  (ADR-0053): oba su posledica praznog mesta u referenci.

## Zapisano za ADR-0033

**Prva:** ADR-0061 je rešio **slučaj**, ne **vrstu**. Napisao sam mehanizam za
„pisac ne sme da pogađa imena" i stavio u njega tačno onaj fajl koji me je tog
dana zaboleo. Trebalo je tada pitati koja još imena pisac mora da napiše a ne
sme da izmisli. **Popravka koja pokriva samo zatečeni primer čeka da je isti
kvar probudi iz drugog ugla.**

**Druga:** pokušao sam da rupu zakrpim **nalazom** — da mu kažem tačno ime polja
umesto da mu dam fajl. Nije prošlo, i dobro je što nije: agent koji prihvati
tvrdnju o fajlu koji ne vidi prihvatio bi i pogrešnu. **Kanal za činjenicu je
referenca; nalaz je kanal za sud.**

**Treća:** pokušaj 2 je pogodio ime polja i pao, pokušaj 3 je stao i rekao šta mu
treba. Oba su ista situacija, a samo drugi je po pravilima. Razlika je došla tek
pošto mu je recenzent rekao da je pogodio — dakle **pravilo 8 radi kad agent zna
da je nešto promašio, a ne pre toga.** To je mera koju treba ponoviti na drugom
zadatku pre nego što se o njoj zaključuje.
