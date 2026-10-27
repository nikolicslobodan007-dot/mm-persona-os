# ADR-0123 — Libri orkestracija: zaseban deterministički pokretač (Veritas faze)

- **Status:** prihvaćeno
- **Datum:** 27.10.2026.
- **Canon verzija:** 1.1
- **Izvori:** ADR-0031 §1 (Veritasovih 8 faza), ADR-0021 (mašina planova),
  ADR-0074 (čovek uvozi), Canon §10.4 (OBSERVED, ne INFERRED), §21.
- **Kod:** `apps/libri/steps.py`, `apps/libri/management/commands/libri.py`
  (radnja `plan`), `tests/test_libri_steps.py`.

## Kontekst

ADR-0031 §1 traži Veritasovih 8 faza (Tragač → … → Čuvar) kao **korake plana**.
Mašina planova (ADR-0021) postoji, ali `AgentPlan.persona` je **obavezan FK** i
handler-i čitaju `step.plan.persona`. Libri je **sloj znanja bez persone** —
dokument i izvor nemaju agenta. Nema sistemske/bibliotekar persone u sistemu
(sve persone su pravi agenti, P-00001…). Dakle Veritas koraci se ne mogu „samo
ukopčati" u ADR-0021 bez odluke.

## Odluka

### 1. Libri NE koristi `AgentPlan` — zaseban scope-ovan pokretač

`apps/libri/steps.py` prati ADR-0021 **obrazac** (faze → ishod → zaustavljanje sa
razlogom, nikad tiho), ali **ne** njegove persona-vezane modele.

Odbijene alternative:
- **`AgentPlan.persona` → nullable:** dira jezgro orkestracije (migracija, audit,
  indeksi, sva logika) i slabi invarijantu „svaki plan pripada agentu" zbog
  domena koji nije o agentima. Pogrešan smer.
- **Lažna „sistem/Bibliotekar" persona:** zagađuje registar agenata (33 → 34) i
  predstavlja orkestraciju znanja kao agenta — semantički krivo.

Libri je genuino drugi domen (determinističko izvođenje znanja, bez odobrenja/
delegiranja) od ponašanja agenta, pa je zaseban tanak pokretač opravdan. Reuse
je stvaran: faze su tanki omot oko već izgrađenih `tvrdnje`/`entiteti`/
`pouzdanost`/`dosije` funkcija.

### 2. Faze mapirane na postojeći deterministički sloj

| Veritas faza | Libri |
|---|---|
| Tragač | `uvoz` (preduslov — dokument postoji) |
| Čitač | `tvrdnje.upisi` (4a) |
| Kartograf + Hroničar | `entiteti.upisi` (4b — graf + dvostruko vreme) |
| Proveravač | `pouzdanost.upisi` (4b+) |
| Inspektor | kontradikcije (već u dosijeu iz pouzdanosti; §9/§10 kasnije sa LLM) |
| Bibliotekar | `dosije.sastavi` (4c) |
| Čuvar | invarijanta u svakoj: izvor + blokovi, OBSERVED, bez izmišljanja |

### 3. Idempotentno i bez tihih padova

Svaki `upisi` je delete+recreate po izvoru, pa je ponovno pokretanje bezbedno.
Faza koja padne (`ValueError`) zaustavlja tok uz `LibriPlanError` sa **imenom
faze i razlogom** — nikad tiho. Čuvar odbija dokument bez izvora/blokova pre
početka (licenca je već gejtovana na uvozu, ADR-0074 — `ZABRANJENA` ne uđe).

### 4. LLM faze kasnije iza istih potpisa

Hipoteze (§9) i otvorena pitanja (§10) ulaze kad LLM sloj bude izabran, **iza
istih potpisa faza**, bez promene toka.

## Posledice

- Komanda `libri plan --dokument <id> --actor user:` pokreće ceo tok i ispiše
  rezultat po fazi + dosije. Zove se unutar `bind(actor)` (čovek pokreće, ADR-0074).
- **Bez novog modela/migracije i bez novog audit event-tipa** (konzistentno sa
  postojećim Libri slojem; kapije nedirnute).
- Deterministički i merljiv (radi na sloju koji je već izmeren).
- Kad zatreba orkestracija sa personom (delegiranje, odobrenja nad znanjem),
  može da pređe na pravu ADR-0021 mašinu — ovaj pokretač je tada most, ne zid.
