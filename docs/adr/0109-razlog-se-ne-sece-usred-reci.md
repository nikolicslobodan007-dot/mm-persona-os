# ADR-0109 — Razlog se ne seče usred reči

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Prvi pravi pregled po ADR-0108 radio je tačno ono što treba — šef
  je vratio nacrt i objasnio zašto. Ali čovek je u niti dobio: *„Nacrt ne
  pokazuje da je urađen stvaran posao za vla."* i *„ima li jasan razl"*.
  Obrazloženje i nacrt su bili iseceni usred reči.
- **Prethodi:** ADR-0022, ADR-0024, ADR-0105, ADR-0108
- **Menja:** `apps/orchestration/plans.py`, `apps/orchestration/razgovor.py`,
  `apps/content/pregled.py`, `apps/content/steps.py`, `tests/test_razgovor.py`

## Odluka

**1. Seče se na razmak, nikad usred reči.** `plans.shorten(tekst, granica)`
skraćuje na poslednju celu reč i dodaje „…" **samo** ako je stvarno skratio.
Tekst koji staje u granicu vraća se netaknut, bez tri tačke.

**2. Razlog u predaji posla nagore ide do 1000 znakova** (`[:300]` je bio
razlog gornjeg kvara). Razlog putuje kroz jednu predaju, retko je dugačak, a
kad jeste — to je obrazloženje šefa i čovek ga čita.

**3. Primedba pregleda ide do 600 znakova**, a poruka o vraćanju do 700.

**4. U nit ide ceo nacrt iz baze, ne izlaz koraka.** `content.draft` u izlazu
nosi prvih 400 znakova — dovoljno za zapis u planu, premalo za čoveka koji
treba da presudi. Direktor sada čita `ContentItem.body`, skida potpis
izvršioca (ADR-0108) i prikazuje do 4000 znakova. Kad nacrta više nema u bazi,
vraća se ono što je ostalo u koraku: bolje početak nego ništa.

## Šta ovo NE radi

- **Ne ukida granice.** Poruka u niti i dalje ima plafon; samo je pomeren tamo
  gde ne kvari smisao rečenice.
- **Ne dira zapis u planu.** `content.draft` i dalje upisuje skraćen tekst u
  `output_json` — plan je trag, ne skladište sadržaja.
