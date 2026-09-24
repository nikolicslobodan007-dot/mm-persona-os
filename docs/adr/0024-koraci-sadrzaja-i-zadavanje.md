# ADR-0024 — Koraci sadržaja i zadavanje posla

- **Status:** prihvaćen
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0021 (plan sa checkpointima), ADR-0022 (delegiranje), ADR-0023 (zapošljavanje)
- **Canon:** §15.2 (odobrenje i TTL), §9.4 (tvrde zabrane)

## Problem

Posle ADR-0022 šef-agent ume da zada posao izvršiocu. Posle ADR-0023 ima kome
da ga zada. Ali kad se to prvi put spojilo, ispalo je da izvršiocu može da se
zada **samo ništa**: jedini koraci plana bili su poštanski (`mail.draft`,
`mail.send`), a oni traže pristiglu poruku.

Delegiranje bez posla je prazan obred.

## Odluka

Dva koraka od kojih posao počinje, plus jedan koji ga vidljivo zatvara:

- **`content.draft`** — napiši nacrt na zadatu temu. Nema spoljašnjeg efekta,
  pa ne traži odobrenje; tekst iz modela prolazi iste tvrde zabrane kao i
  objava (ADR-0009).
- **`content.submit`** — pošalji nacrt na odobrenje za objavu. Ovo **jeste**
  spoljašnji efekat, pa korak čeka čoveka. Ako persona nema nalog sa pravom
  objave, korak staje **sa razlogom** — ne traži prečicu i ne bira nalog umesto
  čoveka.
- **`plan.note`** — beleška u planu, korak bez ikakvog efekta. Služi da se u
  ispisu vidi da je plan zaista nastavljen posle izvršioca ili posle čekanja.

Uz njih i komandna linija za zadavanje:

```
manage.py plan --persona P-00001 --zadaj P-00002 --tema "Rokovi isporuke u B2B"
```

Šef dobija plan od dva koraka (zadaj → preuzmi), izvršilac svoj plan sa
nacrtom. Komanda odbija nalog nagore ili u drugi sektor pre nego što išta
napravi — ista provera `org.can_delegate` kao u motoru, samo ranije, da
operater dobije razlog odmah.

## Šta je odbačeno

- **Da `content.submit` sam nađe „neki" nalog i objavi.** Nalog nosi oznaku o
  AI prirodi i imenovanog čoveka-administratora; biranje naloga je odluka, ne
  detalj izvršavanja.
- **Da nacrt izvršioca automatski ide na odobrenje.** Šef koji je zadao posao
  prvo preuzima nacrt; predlog objave je zaseban korak koji se zadaje namerno.
- **Generički korak „uradi bilo šta preko modela".** Svaki korak ima ime i
  granice; korak bez granica je alat bez kočnice.

## Posledice

- Prvi pravi lanac radi od kraja do kraja: **čovek → Mila (šef) → Jovan
  (urednik) → nacrt → nazad šefu**, bez ijedne ručne intervencije između.
- Novi agent bez kanala ne može da predloži objavu, i to je tačno ponašanje:
  poverenje i kanal su odvojene, namerne odluke (ADR-0017).
- Otvoreno: tema se za sada zadaje rukom; kasnije je bira planer sadržaja
  (F7) ili šef-agent iz svog plana.

## Dopuna — nacrt kaže ko ga je pisao

Prva proba na serveru je prošla od kraja do kraja, ali je Jovan napisao
šablonsku rečenicu, ne tekst iz modela: **novi agent nema svoj ključ**, pa je
gateway pao na lokalni šablon. To je ispravna rezerva (ADR-0009) i nije kvar —
ali je bila **nevidljiva**, a nacrt koji je napisao šablon ne sme da izgleda
kao nacrt koji je napisao model.

Zato `content.draft` sada upisuje i `model` (`anthropic/claude-sonnet-5` ili
`local/template-v1`), a komanda ga ispisuje i upozorava kad je pisao šablon.

Isto važi za odbijen nacrt: ako `content.draft` vrati stavku koja nije
`DRAFT` (ponavljanje, tvrda zabrana), korak **pada sa razlogom** umesto da
prijavi `DONE`. Odbijen nacrt nije obavljen posao, i nalogodavac to mora da
vidi.

## Kod

- `apps/content/steps.py` — `content.draft`, `content.submit`
- `apps/orchestration/plans.py` — `plan.note`, `HANDLER_MODULES`
- `apps/orchestration/management/commands/plan.py` — `--zadaj`, `--tema`
- `tests/test_delegation.py::TestPosao` (3 provere)
