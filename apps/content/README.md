# `apps/content` — sadržaj koji persona pravi i objavljuje

ADR-0043. Ovaj app drži sadržaj i put od ideje do objave: ideja, nacrt,
odobrenje, praćenje objave. Granica prema `apps/channels` je namerno uska —
ovde ne žive nalozi, platforme ni ograničenja platforme.

## Put sadržaja

1. **Ideja** (`ContentIdea`) — jeftin red, nastaje u desetinama dnevno.
   Dedup po normalizovanoj temi (`dedupe_key`), po potrebi vezana za
   `WorldEvent` ili `MemoryItem` iz kojeg je potekla.
2. **Nacrt** (`ContentItem`, status `DRAFT`) — pravi ga `service.draft()`
   kroz memoriju i LLM Gateway. Ovo je **unutrašnji** korak: nema spoljni
   efekat, ne ide kroz policy, ne traži odobrenje. Tekst iz modela prolazi
   iste tvrde zabrane kao i objava, proverava se Rečnikom uz Pravopis
   (ADR-0055/ADR-0056) i upoređuje sa ranijim objavama radi ponavljanja
   (Canon §16.3 — prag u `REPETITION_THRESHOLD`).
3. **Predlog objave** (`service.submit()`) — tek ovde sadržaj dobija
   spoljni efekat: pravi se `Action` i ide kroz `apps.policy` (ADR-0009).
   Svaka javna objava je A2. `ContentItem.status` ide u `IN_REVIEW`.
4. **Odobrenje** — čovek odlučuje kroz `apps.policy` (`ApprovalRequest`).
   Odobrenje može doći i sa izmenom teksta (`APPROVED_WITH_CHANGES`);
   `sync_from_action()` tada upisuje novi `content_hash` i diže `version`.
5. **Objava** (`Publication`) — kanal-specifičan zapis sa `provider_post_id`
   i statusom koji prati izvršenje akcije (`PublicationStatus`). Isti
   `ContentItem` može imati više `Publication` zapisa (isti tekst na više
   naloga), svaki sa svojom akcijom.
6. **Praćenje** (`consumers.sync_publication`) — status sadržaja i objave
   nikad se ne menja ručno; prati stanje `Action` preko eventa
   (`approval.resolved`, `action.queued`, `action.succeeded`,
   `action.failed`, `action.blocked`). Idempotentno, at-least-once (ADR-0009).

## Moduli u ovom app-u

- `models.py` — `ContentIdea`, `ContentItem`, `ContentAsset`, `Publication`,
  `EditorialLesson`.
- `service.py` — glavna putanja: `create_idea`, `draft`, `submit`,
  `sync_from_action`, `plan_post_for_run`, `draft_now` (ručni nacrt sa
  konzole, ADR-0012).
- `consumers.py` — potrošač evenata koji drži sadržaj usklađen sa akcijom.
- `planner.py` — most između buđenja persone i `service.plan_post_for_run`.
- `steps.py` — koraci plana (`content.draft`, `content.submit`) za
  delegirane zadatke (ADR-0024).
- `tasks.py` — Celery zadatak `content.draft_for_run` za asinhroni nacrt.
- `lessons.py` — pouke urednika: iz odbijanja i izmena (ADR-0014), sektorska
  pravila (ADR-0017) i kućni stil cele firme (ADR-0054). Idu doslovno u
  svaki prompt za pisanje, sa eksplicitnom naznakom kad su odsečene.
- `pravopis.py` — kućni stil izveden iz Pravopisa srpskoga jezika, sa brojem
  tačke uz svako pravilo (ADR-0054).
- `recnik.py` — Rečnik uz Pravopis kao izvor znanja i kao provera gotovog
  teksta nad oblicima koje knjiga izričito odbija (ADR-0055/ADR-0056).
  Podaci dolaze iz `data/recnik-uz-pravopis.jsonl`.
- `management/commands/` — `kucni_stil` (upis/pregled kućnog stila),
  `recnik` (uvoz i provera Rečnika), `content_eval` (merenje ruta za
  nacrte na istim temama, ADR-0011).

## Granica prema `apps/channels`

`apps/channels` drži naloge, platforme i njihova ograničenja (kapaciteti,
rate limit, disclosure po platformi). `apps/content` zna samo da postoji
`ChannelAccount` sa pravom objave (`content.publish_approved` capability) —
ne zna ništa o tome kako platforma radi. Izbor naloga (`publish_channel()`)
gleda status naloga i nivo poverenja, ne platformska pravila; ona primenjuje
adapter u `apps.runtime`. SANDBOX nalog je jedini dozvoljen dok je persona u
SIMULATION/SHADOW okruženju — ovo pravilo živi u `apps/content`, jer je
odluka o tome ŠTA sme da izađe, ne KAKO se šalje.
