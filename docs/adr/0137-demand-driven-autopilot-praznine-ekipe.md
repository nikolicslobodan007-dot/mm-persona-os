# ADR-0137 — Demand-driven autopilot: dnevni ulov ka prazninama ekipe

- **Status:** prihvaćen (11.11.2026.)
- **Povod:** Dnevni autopilot (ADR-0130) vukao je po FIKSNOJ listi tema
  (`TEME_PODRAZUMEVANE`). Stavka 1 (ADR-0132) je dala meru praznine po nišama,
  ali autopilot je nije koristio. Treba zatvoriti petlju: ulov ide ka onome
  što ekipi STVARNO fali.
- **Prethodi:** ADR-0132 (potraznja), ADR-0130 (dnevni autopilot), ADR-0131
- **Menja:** `apps/memory/management/commands/potraznja.py` (`praznine_ekipe`),
  `apps/memory/tasks.py` (dnevni task), testovi.

## Odluka
`praznine_ekipe()` meri prazninu po **distinct nišama cele ekipe** (ne
persona×niša — jeftino i kad ekipa naraste): za svaku nišu `najbliza_distanca` +
`broj_u_diviziji` → `_praznina`. Vraća praznine od najveće razdaljine.

Dnevni task (`github_signals_dnevno`) temu ulova pravi kao **union** podrazumevanih
tema i praznina ekipe, i beleži praznine (demand). Union znači:
- **nikad ne skida manje** nego do sada (default teme ostaju);
- praznine **usmeravaju** mrežu ka onome što fali;
- praznine koje izvor (GitHub Signals = tech/AI repoi) ne pokriva **tiho ne daju
  ništa** — nema štete.

Ljudska kapija uvoza ostaje (ADR-0130): auto-uvoz samo SLOBODNA.

## Granice (pošteno)
- GitHub Signals pokriva tech/AI domen; poslovne praznine (npr. „strategija")
  ne daju github rezultate — za njih treba drugi izvor (kasnije). Zato je ovo
  union (default + demand), ne zamena.
- v1 širi mrežu ka prazninama; PRIORITIZACIJA gap-repoa u top-N je sledeći korak.
- Praznine se za sada beleže u log; površina (konzola/Telegram) je kasnije.

## Posledica
Dnevni ulov više nije „guraj fiksnu listu" nego gleda šta ekipi fali —
zatvara petlju potraznja → ulov.
