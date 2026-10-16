# Izvor: alirezarezvani/claude-skills

- uri:          https://github.com/alirezarezvani/claude-skills
- licenca:      MIT (navedena i u LICENSE i u svakom SKILL.md: `license: MIT`)
- license_box:  SLOBODNA
- license_note: MIT
- commit_sha:   19392f7a08264ed00486a251f5b2098321771f94
- preuzeto:     16.10.2026.

## Šta je uvezeno

374 jedinstvene veštine iz 388 `SKILL.md` fajlova (razlika = duplikati po imenu).
Mirror pod `.gemini/` (458 fajlova) je preskočen — isti sadržaj.

| fajl | file_path za KnowledgeSource | veština |
|---|---|---|
| claude-skills-razvoj.json | korpus/vestine/claude-skills-razvoj.json | 151 |
| claude-skills-uprava.json | korpus/vestine/claude-skills-uprava.json | 62 |
| claude-skills-marketing.json | korpus/vestine/claude-skills-marketing.json | 56 |
| claude-skills-operativa.json | korpus/vestine/claude-skills-operativa.json | 20 |
| claude-skills-kvalitet.json | korpus/vestine/claude-skills-kvalitet.json | 17 |
| claude-skills-proizvod.json | korpus/vestine/claude-skills-proizvod.json | 17 |
| claude-skills-istrazivanje.json | korpus/vestine/claude-skills-istrazivanje.json | 15 |
| claude-skills-komercijala.json | korpus/vestine/claude-skills-komercijala.json | 13 |
| claude-skills-projekti.json | korpus/vestine/claude-skills-projekti.json | 9 |
| claude-skills-uskladjenost.json | korpus/vestine/claude-skills-uskladjenost.json | 9 |
| claude-skills-finansije.json | korpus/vestine/claude-skills-finansije.json | 5 |

## Kako je napravljeno

Mehanički, skriptom — nije prepisivano rukom i nije izmišljano:
- `ime` = `name` iz frontmattera izvornog SKILL.md
- `koraci` = numerisani koraci iz tela; ako ih nema, naslovi odeljaka; ako ni njih,
  stavke liste. Organizacioni naslovi bez postupka ("Workflow", "Rules", "References"…)
  su izbačeni.
- `napomene` = `description` iz frontmattera + putanja izvornog fajla
- `pouzdanost` = 0.7 za sve (tuđi izvor, po ADR-0098)
- jezik izvornika: engleski; nije prevođeno, da se ne bi menjalo značenje

## Otvoreno

- 1 veština ima manje od 3 koraka (`caveman`) — bezopasno, može i da se izbaci.
- Nisu prevedene na srpski. Ako hoćemo prevod, to je poseban prolaz kroz model.
