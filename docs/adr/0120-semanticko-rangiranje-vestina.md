# ADR-0120 — Semantičko rangiranje veština (MiniLM-L12)

- **Status:** prihvaćen (19.10.2026.)
- **Povod:** Veštine su engleske (prave, sa koracima), agenti rade na srpskom.
  Leksičko poklapanje ne premošćuje jezik, pa prava veština ostaje zakopana.
  Izmereno (zlatni skup veština): leksički `puni@4=4/11, MRR=0.269` — prava
  veština na rangu 121, 177, 308, 444.
- **Prethodi:** ADR-0101 (rang veština), ADR-0112/0113 (indeks+pune, budžet),
  ADR-0009/§10.5 (embedding sloj je zamenljiv, model se bira merenjem)
- **Menja:** `apps/memory/embeddings.py` (provajder MiniLM), `config/settings/base.py`
  (VESTINA_EMBEDDING_*), `apps/memory/models.py` (model `KnowledgeEmbedding`) +
  migracija, `apps/memory/context.py` (semantičko rangiranje), `apps/memory/vestine.py`
  (embed pri uvozu), nova komanda `embed_vestine`, `apps/memory/golden_vestine.py` +
  `vestina_eval`, `pyproject.toml` + `constraints.txt` + `Dockerfile` (fastembed + model
  pečen u imidž), testovi.

## Odluka

**1. Memorija se NE dira.** `local-hash` daje hit@5=1.00 na memoriji — savršeno.
Problem je samo kod veština. Zato MiniLM ide **samo na veštine**, bez migracije
memorije, bez promene globalnog `EMBEDDING_DIM`.

**2. Model: `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, ~220 MB), lokalno
preko `fastembed` (ONNX).** Izmereno protiv kandidata (Canon §21):

| model | VEŠTINE puni@4 | VEŠTINE MRR | MEMORIJA MRR |
|---|---|---|---|
| osnova (leksički) | 4/11 | 0.269 | 0.92 |
| **MiniLM-L12 (izabran)** | 7/11 | **0.588** | 1.0 |
| mpnet-base (4,5× veći) | 8/11 | 0.617 | 1.0 |

MiniLM je 2,2× bolji, staje u 4 GB bez skoka servera, radi offline (model pečen
u imidž), naši podaci ne izlaze. `e5-large` kao buduća nadogradnja —
`claude/nadogradnja-embedding-e5-large.md`.

**3. Vektor veštine je zaseban zapis.** Nova tabela `KnowledgeEmbedding`
(FK `KnowledgeFact`, `model_key`, `dimensions`, vektor 384) — preslikava
`MemoryEmbedding` (re-embed bez diranja činjenice, §10.5). Embed se pravi pri
uvozu veštine i komandom `embed_vestine` (backfill).

**4. Rangiranje je kosinusna sličnost.** Za zadat upit, veštine se rangiraju po
`CosineDistance` nad `KnowledgeEmbedding`; pune (koraci) idu vrhu ranga, ostalo
indeks (ADR-0112). Bez upita ili bez embeddinga — pad na stari leksički rang
(ADR-0101), sistem radi i bez modela (ADR-0009).

## Granica / nadogradnja

`e5-large` (1024, 16 GB server) — kada poraste broj agenata i veština; koraci su
u `claude/nadogradnja-embedding-e5-large.md`. fastembed se uvodi sad, pa je
nadogradnja samo nov provajder + re-embed.
