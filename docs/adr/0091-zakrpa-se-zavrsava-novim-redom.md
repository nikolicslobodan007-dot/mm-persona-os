# ADR-0091 — Zakrpa se završava novim redom

- **Status:** prihvaćen (14.10.2026.)
- **Povod:** Aider je prvi put napisao ispravnu zakrpu — i obe su odbijene sa
  `apply --check: error: corrupt patch at line 244`. Izgledalo je kao da je
  agent napisao neispravan diff. Nije.
- **Prethodi:** ADR-0090 (rok pisca), ADR-0089, ADR-0086 (šav za Aidera),
  ADR-0052/0066/0067 (prepravke hunkova), ADR-0033
- **Menja:** `apps/orchestration/pisac.py` — `_zavrsi_redom`, pozvana na
  Aiderovom putu. `tests/test_pisac.py` — jedan test.
- **Canon:** §7.3

## Izmereno

Obe zakrpe, iz baze:

```
16:31  REJECTED  znakova: 10276  | kraj: '… assert "vestina iz izvora dva" not in izlaz'
16:38  REJECTED  znakova: 10147  | kraj: '… assert "vestina iz izvora dva" not in izlaz'
```

Zakrpa ima **244 reda**, i 244. je poslednji. `repr` pokazuje da iza njega nema
`\n`. `git apply` traži završni red i bez njega javlja „corrupt patch" na
poslednjem redu — tačno ono što smo dobili.

Prva slutnja je bila odsecanje na `MAX_DIFF_ZNAKOVA = 20_000`. **Oborena**:
10 276 i 10 147 znakova, daleko ispod praga. Zapisuje se da ne bi neko sutra
krenuo istim pogrešnim tragom.

Put kojim je red nestao, sve izmereno:

| Mesto | Šta radi |
|---|---|
| `git diff --cached` | piše završni red, kao i svaki `git diff` |
| `gateway.py:291` | `Generation(text.strip(), …)` — **jede ga** |
| `pisac.py:584` | na Aiderovom putu `g.text` je već diff, pa `izvuci_diff` (koje bi ga dopisalo) se namerno preskače |
| `zakrpa.py:699, 775` | prepravke hunkova čuvaju završni red **samo ako ga ulaz ima** — a nema ga |

Nijedan od ta četiri koraka nije pogrešan sam za sebe. Pogrešan je šav između
njih, a njega sam pisao ja (ADR-0086).

## Odluka

Zakrpa se završava novim redom, i to se obezbeđuje na mestu gde tekst ponovo
postaje zakrpa — `_zavrsi_redom` na Aiderovom putu u `pokusaj`.

`gateway.generate` se **ne dira**. `strip()` je ispravan za odgovor modela, a
gateway ne sme da zna da ponekad nosi zakrpu — to bi mu bila druga uloga.

## Šta se ovim NE menja

Naš put (`izvuci_diff`) je završni red dopisivao i ranije; tamo nema izmene.

Otvoreno: obe odbijene zakrpe stoje u bazi sa potrošenim pokušajima (2/8) i
plaćenim centima (80/300). Tako i treba — odbijena zakrpa je podatak (ADR-0038
§3), a plaćeni poziv mora negde da stoji (ADR-0044). Zadatak se nastavlja sa
trećim pokušajem, ne briše mu se istorija.
