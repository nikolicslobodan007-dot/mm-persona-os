# ADR-0042 — Merenje rada agenta

- **Status:** prihvaćen (25.09.2026.)
- **Prethodi:** ADR-0034 §6 (merenje, obećano), ADR-0035 (kapije), ADR-0038 (zakrpa),
  ADR-0040 (red), ADR-0033 (pravilo nula)

## Zašto sada

ADR-0034 §6 je obećao merenje po agentu i ostavio ga nenapravljenim. Posledica je da
**svako „dok ne bude izmereno" u ostalim ADR-ovima znači „nikad"**:

- ljudska kapija pred `main` stoji „dok ne postoji izmeren učinak" (ADR-0038 §6);
- pravo šefa-agenta da deli poverenje čeka meru njegovog rada (ADR-0037);
- izbor modela za pisanje koda traži poređenje, a poređenje traži brojeve.

Dok merenja nema, svaka od tih odluka je zamrznuta, a izgleda kao da je odložena.

## Odluka

`manage.py ucinak [--persona | --sektor]` daje po agentu: zadatke i završene,
predate zakrpe i njihov ishod, **pokušaje u zaštićenu zonu**, udeo kapija prošlih iz
prvog puta, i nalaze recenzenta na njegov rad.

### 1. „Iz prvog puta" znači prvi pokušaj

Mera je po trojci **(zadatak, zakrpa, kapija)** i gleda **prvi** upisani ishod. Posle
popravke svako prođe iz drugog ili trećeg puta; razlika između prvog i trećeg je
jedino što nešto govori o agentu. Zato `GateResult` i čuva svaki pokušaj (ADR-0035 §3)
— bez istorije ove mere ne bi bilo.

Nova zakrpa je nov posao i njene kapije su svoje merenje (ADR-0040).

### 2. Ono što nema izvor ostaje `None`, ne nula

Trošak po zadatku i „greške kasnije vraćene na njegov commit" ADR-0034 §6 traži, a
izvora za njih još nema: LLM poziv po zadatku ne postoji (čeka drugu polovinu
ADR-0041), a vraćanja se ne prate.

Nula bi tvrdila da je mereno i da je ispalo nula. **Broj koji niko ne može da
potkrepi gori je od nedostajućeg** (ADR-0033). Zato stoji `None`, a uz svaki ispis ide
spisak `ne_meri_se` — da se ne zaboravi da je izostavljeno namerno.

### 3. Odbijena zakrpa je podatak

Agent koji stalno gura u zaštićenu zonu ili izvan svog dela koda vidi se **samo**
ovde. Zato se odbijene zakrpe pamte (ADR-0038 §3) i zato se broje posebno.

## Šta je odbačeno

- **Jedna ocena po agentu.** Zbir koji spaja brzinu, tačnost i poslušnost ne govori
  ništa, a zvuči kao da govori sve.
- **Poređenje agenata po broju zadataka.** Zadaci nisu iste težine; mera bez težine
  nagrađuje onog ko uzima lakše.
- **Nula umesto nedostajućeg podatka.**
- **Automatsko podizanje poverenja po dobrim brojevima.** Merenje je ulaz u odluku,
  ne odluka. Poverenje i dalje daje čovek (ADR-0037 §4).

## Posledice

- `apps/orchestration/ucinak.py`, `manage.py ucinak`, `tests/test_ucinak.py` (15 provera).
- Kad druga polovina ADR-0041 proradi, trošak po zadatku dobija izvor i izlazi iz
  `ne_meri_se`.
- Odluke koje su čekale merenje sada imaju na šta da se oslone — ali se ne otvaraju
  same od sebe.
