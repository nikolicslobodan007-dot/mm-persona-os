# ADR-0044 — Pisac zakrpe

- **Status:** prihvaćen (26.09.2026.) — zatvara **drugu polovinu ADR-0041**
- **Prethodi:** ADR-0041 (brif), ADR-0038 (zakrpa), ADR-0040 (red), ADR-0042
  (merenje), ADR-0043 (grana), ADR-0009 (LLM Gateway), ADR-0026 (ključ po agentu),
  ADR-0033 (pravilo nula)

## Problem

Lanac je bio ceo osim jednog mesta: **zakrpu je i dalje kucao čovek.** Brif
postoji, kapije mere, grana se otvara, učinak se broji — a onaj ko piše je
nedostajao. Dok je tako, „departman za programiranje" je mašina koju pokreće
ruka.

ADR-0041 je tri brojke ostavio kao poslovne odluke. Dve su to i bile, a jedna
nije: **izbor modela nije odluka u kodu nego podešavanje rute** (ADR-0009,
ADR-0026). Zapisivanje toga kao „blokirane odluke" bilo je moja pretpostavka
(ADR-0033).

## Odluka

`manage.py pisac --zadatak TSK-…` pravi **jedan pokušaj**: brif → model → zakrpa.

### 1. Ovo nije petlja, i ne sme da bude

Kapije se vrte u poslušniku, van aplikacije, jer aplikacija nikada ne dobija
`docker.sock` (ADR-0038 §2). Petlja koja bi ovde čekala ishod morala bi ili da
dobije Docker, ili da drži radnika dok neko drugi meri.

Zato je krug raspoređen kroz red, a ne kroz `while`:

```
pisac → zakrpa → (poslušnik) kapije → pisac čita ishod iz brifa → …
```

Povratna informacija već postoji: brif nosi pale kapije sa ispisom i otvorene
nalaze (ADR-0041 §4). Ništa novo nije trebalo izmišljati.

### 2. Tri brojke

- **Plafon troška: 60 centi po zadatku.** Proverava se **pre** svakog poziva.
  Posle poziva se trošak ne može poništiti, pa plafon sme da bude prekoračen za
  najviše **jedan poziv** — a jedan poziv je ograničen veličinom brifa (200 KB,
  ADR-0041 §1). To se kaže naglas umesto da se tvrdi tvrda granica koje nema.
- **Najviše 3 pokušaja po zadatku.** Broje se **zakrpe**, ne pozivi: plaća se
  ishod, ne trud.
- **Prekidač „nema napretka"** staje i pre ta dva, na dva znaka:
  ista zakrpa koja je već predata (otisak nad normalizovanim tekstom), ili dve
  uzastopne izmerene zakrpe koje obaraju **iste** kapije.

Sve tri se menjaju zastavicom (`--plafon`, `--najvise`), a provera im je na
**jednom mestu** (`pisac.zasto_ne`) — da komanda ne bi proveravala jedno a
servis drugo.

### 3. Neuspeo poziv se pamti, sa troškom

Odgovor koji nije diff (uključujući ispravno „NE MOGU: …") upisuje se kao
odbijena zakrpa, sa cenom poziva. Dva razloga, oba o poštenju:

- **poziv je plaćen**, pa trošak mora negde da stoji;
- **pokušaj se desio**, pa mora da uđe u plafon.

Prećutan neuspeh bi značio besplatan i beskonačan krug — tačno onu petlju koja
je 25.09. već jednom pojela pola sata procesora (ADR-0040).

### 4. Lokalni šablon nije agentov neuspeh

Ako zahtev padne na lokalni šablon (ADR-0009), pisac **staje sa greškom** i ne
upisuje ništa. Šablon ne piše kod; njegov odgovor nije rad agenta i ne sme da mu
pokvari meru.

Isto važi unapred: bez ijedne spoljne rute za `code_patch`, pokušaj se ne pravi,
a poruka kaže šta tačno nedostaje.

### 5. Izbor modela je ruta, ne kod

Nova svrha `LLMPurpose.CODE_PATCH` — svoja, a ne `content_draft`, jer traži drugu
rutu, veći plafon izlaza i svoj budžet (Canon §13.2). Model se bira postojećom
komandom, bez ijedne izmene koda:

```
manage.py llm_route add --purpose code_patch --provider anthropic \
    --model <model> --ne-trenira --max-output 8000 --in-usd … --out-usd …
manage.py llm_route enable --purpose code_patch --provider anthropic --model <model>
```

Uslovi iz ADR-0009 stoje netaknuti: `LLM_EXTERNAL_ENABLED=true`,
`data_training_allowed`, i postojeći `credential_ref`. Agent sme i svoju rutu
(ADR-0026).

**Koji model — odlučuje merenje, ne ovaj ADR.** `ucinak` daje udeo „iz prvog
puta" i trošak po agentu; dve rute se porede time, a ne tvrdnjom.

### 6. Trošak izlazi sa spiska neizmerenog

`TaskPatch.cost_eur_cents` nosi cenu poziva iz kog je zakrpa nastala. `ucinak`
ga sumira, pa „trošak po zadatku" — koji ADR-0034 §6 traži, a ADR-0042 je s
pravom ostavio kao `None` — **sada ima izvor** i izlazi iz `ne_meri_se`.

Zakrpa koju je kucao čovek ostaje `None`, ne nula: nula bi tvrdila da je model
pozvan i da je bio besplatan.

## Šta je odbačeno

- **Petlja u aplikaciji koja čeka kapije.** Traži `docker.sock` ili blokiranog
  radnika. Red to već rešava.
- **Ceo repozitorijum u prompt.** Odbačeno još u ADR-0041 i ostaje odbačeno.
- **Plafon u broju tokena.** Tokeni nisu novac; dve rute sa istim brojem tokena
  koštaju različito.
- **Automatsko podizanje plafona kad pokušaj ne uspe.** Zadatak koji ne staje u
  60 centi i tri pokušaja nije uzak dovoljno — deli se.
- **Nagađanje diffa iz proze.** Ono što ne liči na diff se ne popravlja
  heuristikom; upisuje se kao neuspeh sa razlogom.

## Posledice

- `apps/orchestration/pisac.py`, `manage.py pisac`, `zakrpa.zabelezi_neuspeh`.
- `LLMPurpose.CODE_PATCH`; migracije `orchestration 0008`, `llm_gateway 0005`,
  `memory 0005` (samo `choices`).
- `tests/test_pisac.py` (30 provera).
- **Izmenjen test iz ADR-0042.** `test_spisak_neizmerenog_ide_uz_rezultat` je
  tvrdio da trošak nije meren; to više nije istina, pa test sada brani suprotno.
  Zapisano jer je promena tvrdnje, ne popravka.
- Na spisku `ne_meri_se` ostaje jedna stavka: greške kasnije vraćene na commit
  agenta. Izvora i dalje nema.

## Šta ostaje otvoreno

- **Prvo pravo merenje.** Dok ruta nije uključena, ovaj ADR je mehanizam bez
  brojeva. Prvi zadatak koji model napiše ide uz čoveka pored ekrana, kao i prvi
  prolaz poslušnika (ADR-0038).
- **Ko pokreće pisca.** Zasad ruka, kao i poslušnik. Beat tek kad se odleži.
