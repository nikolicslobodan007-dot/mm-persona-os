# ADR-0090 — Rok pisca nije rok rute

- **Status:** prihvaćen (14.10.2026.)
- **Povod:** Posle ADR-0089 Aider je prvi put stvarno pozvao model — i oba
  pokušaja su presečena na 60. sekundi, pa prijavljena kao `NETWORK`:
  „mreža nije propustila poziv". To nije bila mreža. Mi smo ga ubili.
- **Prethodi:** ADR-0089 (vraćen coder nije obavljen posao), ADR-0086 (šav za
  Aidera), ADR-0033
- **Menja:** `apps/orchestration/pisac.py` — `ROK_SEKUNDI`, nova šifra
  `ROK_ISTEKAO`, pet novih rečenica u `_RAZLOG_RUTE`.
  `tests/test_pisac.py` — jedan test.
- **Canon:** §13

## Izmereno

Sve rute u bazi, 14.10.:

```
code_patch    10    anthropic claude-sonnet-5   60
code_patch  1000    local     template-v1       60
content_draft 10    anthropic claude-sonnet-5   60
content_draft 1000  local     template-v1       60
reply         10    anthropic claude-sonnet-5   60
reply       1000    local     template-v1       60
```

`LLMRoute.timeout_seconds` je **60** svuda, i to je ispravno za ono što taj
broj znači: koliko sme da traje **jedan poziv provajderu** u
`gateway._call_external`.

`pisac._aiderom` je taj isti broj prosleđivao `subprocess.run` kao rok za
**celu Aiderovu sesiju** — a ona nije jedan poziv: Aider pročita brif i 22
fajla, pa vodi razgovor od više poziva. Dva pojma su bila poistovećena.

## Odluka

Rok pisca je svoj: `PISAC_ROK_SEKUNDI`, podrazumevano **900** (15 minuta).
Stoji u okruženju da se menja bez ponovne gradnje slike, kao i `PISAC`.

Prekoračenje roka više nije `NETWORK` nego **`ROK_ISTEKAO`**. Mreža nije kriva
kad je mi presečemo, a šifra koja laže o uzroku skuplja je od svakog roka
(ADR-0033).

Usput su u `_RAZLOG_RUTE` upisane rečenice za `PRAZNA_ZAKRPA`, `AIDER_ERROR`,
`AIDER_NO_REPORT` i `AIDER_UNMEASURED` — sve su do sada izlazile čoveku kao
gole šifre.

## Šta se ovim NE menja

`LLMRoute.timeout_seconds` ostaje 60 i ostaje rok za jedan poziv. Ovaj ADR ga
ne dira, samo prestaje da ga pozajmljuje za posao koji nije poziv.

Otvoreno, zapisano da se ne izgubi: kad rok istekne, proces se ubija pre nego
što napiše izveštaj, pa tokeni koji su do tada poslati **ne ulaze** u `LLMUsage`
ni u `CostLedger`. Knjige tada ne lažu, ali ne znaju — a to je razlika koju
treba imenovati i zatvoriti zasebnim ADR-om. Jedan ADR, jedna izmena.
