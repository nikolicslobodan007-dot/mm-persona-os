# ADR-0122 — Persona OS je jezgro; domeni su iznad njega

- **Status:** prihvaćen (22.10.2026.)
- **Povod:** Tri specifikacije biraju tri različita tehnološka steka — Persona OS
  (Django / Python / Celery / Postgres / MinIO, **napravljeno i na produkciji**),
  Libero Libri M21 (TypeScript / NestJS / BullMQ) i PickStar V20
  (NestJS / FastAPI / Temporal). Jedan čovek ne održava tri steka. Odluka je
  stajala nezapisana i blokirala ADR-0031.
- **Prethodi:** ADR-0001 (Canon), ADR-0033 (meri, ne pretpostavljaj)
- **Izvor:** `claude/nalaz-libero-libri-pickstar.md`, tačka 3 („Odluka koju niko
  još nije doneo")
- **Menja:** danas ništa u kodu — postavlja pravac i odblokira ADR-0031.

## Odluka

**1. Persona OS je jezgro.** Organizacija, planovi, policy, odobrenja, audit,
gateway, memorija i trošak pišu se **jednom**, u Django jezgru koje već radi na
produkciji.

**2. Libero Libri i PickStar su domeni iznad jezgra**, ne zasebne platforme sa
svojim jezgrom. Izdavački domen (Libero Libri) i produkcioni domen (PickStar)
ulaze kao app-ovi i planovi nad istim jezgrom — presedan je `apps/libri`
(ADR-0031).

**3. Next.js ostaje samo lice.** Tamo gde treba bogatiji UI od konzole, frontend
priča sa jezgrom preko postojećeg API-ja; ne nosi svoj jezgro, svoj outbox ni
svoj audit. (Virtual Office je prvi takav sloj — read-only, preko V1.2 bridge-a.)

## Šta je odbačeno

- **Tri odvojena steka.** Značilo bi da se outbox, gateway, odobrenja, audit i
  trošak pišu po drugi i treći put, na drugom jeziku, i da jedan čovek održava
  tri sistema.

## Posledice

- **ADR-0031** (Libri sloj znanja) prelazi iz „predložen" u „prihvaćen" — uslov o
  jezgru je ispunjen.
- Buduće specifikacije domena se **mere prema jezgru**: šta jezgro već daje ne
  piše se ponovo (ADR-0033 — pre nego što se piše, meri se šta već postoji).
- Frontend slojevi (Virtual Office, buduća lica domena) ostaju bez sopstvene
  poslovne logike — read/write isključivo preko API-ja jezgra.
- **Otvoreno, svesno:** ako neki domen zatraži bogat frontend koji konzola ne
  daje, taj Next.js sloj se gradi — ali kao lice nad jezgrom, a ne kao nov sistem.
