# ADR-0022 — Delegiranje po organizaciji

- **Status:** prihvaćen
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0017 (organizacija i dosije), ADR-0021 (plan sa checkpointima)
- **Canon:** §3.11 (poverenje ide po capability-ju), §6.1 (plan), §9 (audit)

## Problem

Od ADR-0017 firma zna ko je kome šef. Od ADR-0021 agent ume da vodi zadatak
kroz više koraka i da stane na odobrenju. Ali šef-agent nije umeo da uradi ono
zbog čega šef postoji: **da posao zada nekome ispod sebe i sačeka ga**.

Bez toga je organizacija samo slika na zidu — tabela sektora koja ništa ne
pokreće. Sa 10.000 agenata to nije kozmetika: ako svaki agent radi samo svoj
posao i ništa ne predaje, ne postoji način da jedan zadatak prođe kroz tri
para ruku, a da neko ostane odgovoran za ishod.

## Odluka

Uvodi se korak plana `org.delegate`. Šef njime zadaje posao izvršiocu; motor
pravi **izvršiočev plan** kod njega, pauzira šefov korak i vraća ga u život
kad izvršilac završi.

### Pet pravila

1. **Posao ide samo nadole, po organizaciji.** `org.can_delegate(šef, izvršilac)`
   propušta samo neposrednog podređenog — onoga čije radno mesto ima
   `reports_to` na šefovo mesto. Nagore ne, u drugi sektor ne, sam sebi ne.
   Izvršilac koji nije `READY`/`ACTIVE` se odbija.
2. **Delegiranje ne daje nijednu dozvolu.** Izvršilac radi sa **svojim**
   poverenjem, svojim kanalima i svojim odobrenjima. Nalog šefa nije
   zaobilaznica za policy engine; ako izvršiocu treba odobrenje, ono se traži
   od čoveka kao i inače (ADR-0017, pravilo „radno mesto nije dozvola").
3. **Veza se upisuje pre nego što izvršilac krene.** Šefov korak dobija
   `output_json.waiting_for_plan` = izvršiočev plan, pa tek onda motor pokreće
   taj plan. Po toj vezi se meri dubina lanca i po njoj se posao vraća — stanje
   je u bazi, ne u pozivnom steku (ADR-0021).
4. **Kad izvršilac ne završi, šefov plan staje sa razlogom.** `_resume_parent`
   prenosi razlog naviše, pa nalogodavac u konzoli vidi *zašto*, a ne samo da
   je „ABANDONED".
5. **Lanac je ograničen.** `MAX_DELEGATION_DEPTH = 3`: šef → izvršilac →
   njegov izvršilac. Četvrti nivo se odbija i odbijanje putuje naviše. Ovo je
   brana protiv agenta koji posao prosleđuje u krug umesto da ga uradi.

### Kako izgleda

```
Mila (šef marketinga)   plan: „Vodim posao"
  1. org.delegate → Jovan ──────┐   korak stoji (RUNNING)
  2. zaključi                   │
                                ▼
              Jovan (urednik)   plan: „Napiši tekst"
                1. nacrt        ✓
                2. objava       ⏸ čeka odobrenje čoveka
                                … odluka …
                                ✓ → plan COMPLETED
  1. org.delegate ✓ ◀───────────┘   posao se vraća Mili
  2. zaključi ✓ → plan COMPLETED
```

Jedna odluka čoveka na Jovanovoj objavi zatvara i Jovanov i Milin plan. Nijedan
od njih nije dobio dozvolu od onog drugog.

## Šta je odbačeno

- **Sinhrono izvršavanje u obrađivaču.** Prva verzija je pokretala izvršiočev
  plan unutar `org.delegate` i vraćala `Done` ako je ovaj odmah završio. Radilo
  je, ali je dubina lanca merena pre nego što je veza upisana, pa se cap nikad
  nije okidao — lanac je mogao u beskraj. Sada motor uvek ide preko `Delegated`.
- **Novo polje `parent` na `AgentPlan`.** Nije potrebno: veza već postoji u
  koraku koji čeka, a migracija bi uvela drugi izvor istine za istu stvar.
- **Delegiranje nagore („molim te odobri ovo").** To je eskalacija, ne posao;
  za nju već postoji `org.escalation_target`, a odobrenje po Canon-u daje čovek.

## Posledice

- Šef-agent može da vodi posao koji sam ne radi, i odgovoran je za ishod.
- Konzola na strani šefa pokazuje „zadato: P-000xx", a na strani izvršioca
  „zadao: <šef>"; `manage.py plan --persona` pokazuje isto iz terminala.
- Audit dobija `plan.delegated` i `plan.handback` — predaja i vraćanje posla su
  zapisani kao i sve ostalo.
- Otvoreno: izvršilac koji stoji na isteklom odobrenju i dalje ostavlja šefov
  korak u `RUNNING` (isto ograničenje kao u ADR-0021). Rešava se kad uvedemo
  isticanje koraka po vremenu.

## Dopuna 24.09. — motor sam učitava obrađivače

Prva provera na serveru (`manage.py plan --handlers`) ispisala je **samo**
`org.delegate`. Razlog: obrađivač postoji tek kad se njegov modul uveze, a
`apps/channels/reply.py` se uvozio jedino kad stigne pošta — u `worker_channel`.

Posledica bi bila plan koji radi u jednom procesu a pada u drugom: `web`
nastavlja plan posle odobrenja, pa bi korak sa `mail.send` tamo dobio
„Nepoznat obrađivač koraka" i plan bi bio odbačen sa netačnim razlogom.
(Zatečeni Milin plan to nije pogodio — na odobrenje se korak samo zatvara, ne
poziva se ponovo — ali bi svaki sledeći korak posle čekanja pogodio.)

Rešenje: `plans.HANDLER_MODULES` + `load_handlers()`, koji `start()`,
`advance()` i `registered()` zovu na ulazu. Uvoz je keširan, pa se ponavlja
besplatno. **Novi obrađivač u novom modulu mora da se upiše u
`HANDLER_MODULES`** — to je jedino mesto koje treba zapamtiti.

## Kod

- `apps/personas/org.py`: `subordinates()`, `can_delegate()`
- `apps/orchestration/plans.py`: `Delegated`, `parent_of()`, `depth_of()`,
  `failure_reason()`, `_resume_parent()`, `@handler("org.delegate")`
- `tests/test_delegation.py` (10 provera), `tests/test_console.py::TestDelegationConsole`
