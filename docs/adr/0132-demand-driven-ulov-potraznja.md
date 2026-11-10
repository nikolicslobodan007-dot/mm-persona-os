# ADR-0132 — Demand-driven ulov: potražnja po nišama persone

- **Status:** prihvaćen (10.11.2026.)
- **Povod:** Ulov veština je do sada bio „guraj redom" (ADR-0127/0130, dnevni
  autopilot vuče po temama iz fiksne liste). Treba obrnuti smer: neka persona
  kaže šta joj fali, pa to postane upit za ulov. Posle ADR-0131 imamo most
  niša↔divizija — isti most meri i prazninu.
- **Prethodi:** ADR-0131 (promocija po domenu), ADR-0120 (semantičko rangiranje),
  ADR-0074 (uvoz pokreće čovek), ADR-0130 (dnevni autopilot sme SLOBODNA)
- **Menja:** `apps/memory/context.py` (`najbliza_distanca`, `broj_u_diviziji`),
  nova komanda `apps/memory/management/commands/potraznja.py`, testovi.

## Odluka

**Praznina = semantički jaz po nišama persone.** Za svaku nišu persone
(`PersonaTagLink`, kategorija `niche`) `potraznja` nađe kosinusnu razdaljinu
NAJBLIŽE SLOBODNA veštine (ADR-0120 vektori). Ako je iznad praga (`--prag`,
podrazumevano 0.45) — tema je **praznina**, i komanda ispiše spreman
`signali --teme "<niša>"` upit.

- Semantika je primarni signal (radi i za niše bez divizije, npr. `ai`, `b2b`);
  broj veština u diviziji ide kao dodatni kontekst i kao fallback kad je model
  offline (praznina = nijedna veština u diviziji).
- **Komanda samo ČITA.** Ne vadi, ne uvozi, ne radi spoljašnju akciju. Uvoz
  sakupljenog i dalje pokreće čovek (`--actor user:`, ADR-0074) — potražnja mu
  samo donese spisak šta vredi uloviti.

## Zašto niše, ne „skorašnji zadaci"

Niše su već popunjene i stabilne, nula nove instalacije, i koriste isti most kao
rangiranje. „Prazninu nad temama na kojima je persona stvarno radila" (iz run
istorije) ostavljamo za sledeći sloj, kad povežemo temu zadatka iz rextova —
tada autopilot može sam da hrani ulov iz stvarne potražnje.

## Posledica
- `potraznja --persona P-00001` daje spisak tema za ulov po Milinim nišama.
- Kuka ka autopilotu (ADR-0130): kasnije dnevni autopilot čita potražnju umesto
  fiksne liste tema. Zasad čovek gleda spisak i pokreće ulov.
