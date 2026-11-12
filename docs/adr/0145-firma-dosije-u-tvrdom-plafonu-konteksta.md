# ADR-0145 — Firma (dosije) mora da stane u tvrd plafon konteksta

- **Status:** prihvaćen (12.11.2026.)
- **Povod:** Posle dodavanja portfolija (PR #92), `firma/dosije.md` je narastao
  (~1950 → ~4800 znakova ≈ 1350 tokena). `context.build` firmu dodaje kao
  FIKSNU sekciju i, kad fiksne sekcije probiju plafon, skraćivao je samo upit —
  ne i firmu. Zato je `token_count` prelazio `max_tokens` i `test_memory`
  (`test_hard_token_cap` 900, `test_context_build` 1200) je padao (1353 > cap).
- **Prethodi:** ADR-0107 (dosije firme u kontekstu), ADR-0096/0101/0112 (budžeti
  memorije i veština).
- **Menja:** `apps/memory/context.py` (skraćivanje firme kad probija plafon).

## Odluka
`token_count` je **tvrd plafon**. Kad fiksne sekcije (persona_core, firma,
stanje, upit, policy) i posle skraćivanja upita i dalje probijaju budžet, i
**firma se skraćuje** dok ne stane. Produkcijski budžeti su veliki (REPLY 3300,
DAILY 5500, CONTENT 4500, RESEARCH 9500), pa firma (~1350) uvek staje i
skraćivanje se NE dešava; aktivira se samo na veštački uskom plafonu (testovi).

## Posledice
- Plafon je ponovo tvrd — `context.build` nikad ne vrati paket veći od zadatog.
- Portfolio u dosijeu ostaje pun u svim produkcijskim profilima.

## Granica (za kasnije — zasebno)
- Portfolio je „always-on": ~1350 tokena ide u SVAKI build, i kad je nebitan
  (prosta objava). Dugoročno vredi razmotriti da se deo portfolija premesti u
  dohvatljivu memoriju (povuče se samo kad je relevantan), umesto u fiksni
  dosije. Zaseban pravac, ne menja se ovde.
