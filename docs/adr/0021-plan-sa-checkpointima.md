# ADR-0021 — Plan sa checkpointima

- **Status:** prihvaćeno
- **Datum:** 24.09.2026.
- **Canon verzija:** 1.1
- **Izvori:** Canon §6.1–6.2, §9.1, §15.3 · ADR-0007, ADR-0016, ADR-0017
- **Kod:** `apps/orchestration/plans.py`, `apps/policy/service.py`,
  `apps/channels/reply.py`, `apps/orchestration/management/commands/plan.py`,
  `console/`, `tests/test_plans.py`
- **Spoljni izvor obrasca:** OpenHuman flows i sub-agent handback (beleške od
  24.09.). Preuzet je obrazac, **nijedan red koda**.

## Kontekst

Do sada je posao agenta bio jedan potez: buđenje → nacrt → akcija. Kad akcija
stane na odobrenje, priča se tu završava. Ako je odbiješ, **ne nastavlja se
ništa i nigde ne piše da je zadatak ostao nedovršen** — nacrt prosto nestane.

`AgentPlan` i `PlanStep` postoje u šemi od F1, a `policy.propose` već prima
`plan_step`. Model je bio tu; motor nije.

## Odluke

### 1. Tri ishoda koraka, nikad tiho

Obrađivač koraka vraća jedno od tri:

- **`Done(output)`** — korak gotov, plan ide dalje;
- **`Waiting(action)`** — korak čeka čoveka; **plan se pauzira ovde**;
- **`Failed(reason)`** — korak ne može da se završi; plan staje, razlog se upisuje.

Isto tako se završava i sam plan: `COMPLETED`, `ABANDONED` (sa razlogom) ili
`EXPIRED`. Nema puta kojim zadatak nestaje bez traga.

### 2. Stanje je u bazi, ne u procesu

Korak pamti svoj ulaz i izlaz (`input_json` / `output_json`). Radno stanje celog
plana se sastavlja iz koraka: izlazi se **sabiraju**, ne prepisuju, pa korak
vidi sve što su prethodni proizveli — po rednom broju i po imenu obrađivača.
Restart ničemu ne škodi; plan se nastavlja odakle je stao.

### 3. Odluka čoveka nastavlja plan

`decide_approval` posle potvrde transakcije zove motor plana:

- **odobreno** → korak `DONE`, plan se nastavlja;
- **odbijeno** → korak `FAILED` sa razlogom, plan `ABANDONED`.

Radi se u `on_commit` i u `try/except`: **kvar motora plana ne sme da poništi
samu odluku o odobrenju.** Neuspeh ide u audit (`plan.resume_failed`).

Akcija koja nije korak nijednog plana prolazi kao i do sada — ništa se ne menja.

### 4. Obrađivači se registruju, ne granaju

`@plans.handler("mail.draft")` upisuje funkciju u registar; korak bira
obrađivača imenom u `input_json["handler"]`. Nepoznat obrađivač se odbija
**pri pravljenju plana**, ne pri izvršavanju — plan koji ne može da se izvrši
ne nastaje.

Plafoni: najviše 24 koraka po planu i 12 koraka po jednom prolazu motora.

### 5. Odgovor na poštu je prvi plan

ADR-0016 je pravio usamljenu akciju `mail.reply`. Od sada je to plan od dva
koraka:

1. **`mail.draft`** — napiši odgovor (memorija, radno mesto, model, čišćenje).
   Nema spoljašnjeg efekta.
2. **`mail.send`** — predloži slanje kroz policy. Akcija traži odobrenje
   (ADR-0017), pa korak vraća `Waiting` i plan staje.

Kad odbiješ odgovor, sada ostaje zapisano **šta je bio zadatak, dokle je
stigao i zašto je stao**. Ranije je ostajala samo otkazana akcija.

## Posledice

- Konzola: kartica **Planovi** na strani agenta — cilj, koraci, stanje svakog
  koraka i na šta se čeka. Komanda `manage.py plan --persona P-00001`.
- Svaki sledeći višekoračni posao (istraživanje pa objava, priprema ponude,
  delegiranje) dobija isti motor — piše se samo obrađivač koraka.
- 484 testa (dodato 10).

## Šta ostaje

- **Delegiranje** (sledeći ADR): korak plana koji šef-agent zadaje izvršiocu.
  Motor je spreman — treba mu obrađivač koji pravi pod-plan kod drugog agenta,
  uz pravilo iz ADR-0017 da radno mesto ne daje nijednu dozvolu.
- Isteklo odobrenje za sada ne dira plan (korak ostaje `RUNNING` dok ga čovek
  ne odluči). Kad se pojavi prvi plan koji sme sam da odustane, to je zaseban
  potez sa svojim pravilom.
