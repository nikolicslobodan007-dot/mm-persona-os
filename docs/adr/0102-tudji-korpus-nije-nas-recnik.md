# ADR-0102 — Tuđi korpus znanja nije naš rečnik

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Posle uvoza 424 tuđe veštine `canon_lint` je prijavio 12
  prekršaja — svi u engleskom tekstu tuđih veština.
- **Prethodi:** Canon §19, ADR-0074 (tačka 3), ADR-0098, ADR-0101
- **Menja:** `tools/canon_lint.py`, `tests/test_canon.py`
- **Canon:** §19, §0.2

## Izmereno

```
[FAIL] ukinuta imena — 12
  korpus/vestine/claude-skills-razvoj.json:833:  ukinuto ime `workload`
  korpus/vestine/claude-skills-uprava.json:534:  ukinuto ime `behavior`
  … 11 puta `behavior`, jednom `workload`
```

Nijedan nije u kodu. Svi su u rečenicama koje je napisao neko drugi:
„…observe user behavior…", „…team workload…".

## Odluka

**1. Canon §19 čuva imena koja MI dajemo stvarima u kodu.** Reč
„behavior" u tuđoj engleskoj rečenici nije ime našeg modula, a „workload"
u tuđoj rečenici nije naš `cognitive_load`.

**2. Tuđi tekst se ne prepravlja da bi prošao naš lint.** ADR-0074 tačka
3 i ADR-0098 kažu da se tuđi izvor ne menja; ispravljanje reči u njemu
bilo bi upravo to, i to zbog razloga koji sa izvorom nema veze.

**3. Granica je po imenu fajla, ne po folderu.** Naši sopstveni korpusi
nose prefiks `nasi-` i proveravaju se kao i svaki naš izvor. Sve ostalo u
`korpus/vestine/` je tuđe i lint ga preskače. Konvencija se sama održava:
sledeći uvoz ne traži nikakvu izmenu lista.

**4. Ovo ide kroz ADR, ne kroz izuzetak u lintu.** Sam lint to traži:
*„Ako je ime namerno, izmena ide kroz ADR (Canon §0.2), ne kroz izuzetak
u lintu."* Ovde ime nije naše — ali odluka o obimu provere jeste naša, pa
stoji zapisana.

## Cena koju svesno plaćamo

Tuđi korpus od sada može da sadrži i `correlation_id`, `ActionExecution`
ili `P-123`, a lint neće reći ništa. Prihvatamo: ti nizovi tamo nisu
imena u našem kodu nego tekst koji agent čita kao znanje. Ako ikada
budemo generisali kod iz korpusa, ova odluka se ponovo otvara — tada bi
tuđi tekst postao naš izvor, a to je druga stvar.
