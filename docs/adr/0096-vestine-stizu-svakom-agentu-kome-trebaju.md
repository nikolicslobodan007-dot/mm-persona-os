# ADR-0096 — Veštine stižu svakom agentu kome trebaju

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Baza znanja ima 14 veština, a vidi ih samo pisac koda. Urednik
  sadržaja, podrška, prodaja — niko od njih ne dobije nijednu. Izmereno 16.10.
- **Prethodi:** ADR-0074, ADR-0059, ADR-0077, ADR-0095, ADR-0033
- **Menja:** `apps/memory/context.py` — `build()` dobija odeljak sa veštinama;
  `apps/memory/models.py` — `MemoryContextPack` pamti koje su veštine ušle;
  `common/enums.py` — plafon za veštine po profilu;
  `apps/content/service.py` — rečenica o doslovnom prepisivanju pokriva i veštine.
- **Canon:** §10.4

## Izmereno

Dva odvojena skladišta, koja se danas nigde ne sretnu:

| Skladište | Čije je | Ko ga čita |
|---|---|---|
| `MemoryItem` | jedne persone | `apps/memory/context.py:99 build()` → svi agenti |
| `KnowledgeFact` (predikat `vestina.postupak`) | firme (`persona=None`), sa licencom | `apps/orchestration/brif.py:266` → **samo pisac koda** |

`apps/memory/context.py` ne pominje `KnowledgeFact` nijednom. Odeljci koje
`build()` sastavlja danas su: `persona_core`, `current_state`, `task_goal`,
`policy_constraints`, `retrieved_memory`. Kandidate bira
`retrieval.retrieve(persona, ...)`, što znači: samo memorija te persone.

Posledica, izmerena na prvom pravom zadatku van koda (16.10., nacrt urednika
Jovana Ilića): tekst je nastao iz opšteg znanja modela i memorije persone.
Nijedna veština koju je čovek doneo, pročitao i odobrio nije učestvovala.

To je naopako. Veštine su ono što je čovek **proverio i pustio u kuću**, a
upravo one ne stižu do agenta koji radi posao pred kupcem.

## Odluka

**1. `build()` dobija odeljak `vestine`.** Stoji između `policy_constraints` i
`retrieved_memory`, kao zaseban odeljak — ne meša se sa memorijom.

Razlog za razdvajanje nije kozmetika: veštine su kućne i čovek za njih
odgovara, memorija je lična i agent je sam stekao. Kad se sliju u jedno, niko
više ne ume da kaže odakle je agent nešto uzeo (ADR-0033).

**2. Ulaze samo veštine iz izvora koji je `is_active` i čija je kutija
`SLOBODNA`.** ZARAZNA, ZABRANJENA i NEPOZNATA ne ulaze u prompt nikada —
ni „samo za probu", ni uz napomenu (ADR-0059). Kutija se proverava pri
sastavljanju paketa, ne pri uvozu, jer se licenca izvora može promeniti posle
uvoza (ADR-0095).

**3. Veštine imaju svoj plafon i ne jedu memoriju.** Nova konstanta
`PROFILE_VESTINE_TOKENS` u `common/enums.py`, po profilu:

| Profil | Veštine |
|---|---|
| REPLY_CONTEXT | 600 |
| DAILY_PLANNER | 1000 |
| CONTENT_CREATION | 1000 |
| RESEARCH | 2000 |
| REFLECTION | 600 |

Ovo su prve brojke, postavljene rukom, a ne izmerene. Tako i pišu — menjaju se
kad merenje kaže da treba, i ta promena ide kroz ADR.

**4. Paket pamti koje su veštine ušle.** `MemoryContextPack` dobija polje
`vestina_ids` (JSON lista), uz postojeće `memory_ids`. Bez toga ne možemo da
odgovorimo na pitanje „na šta se agent oslonio kad je ovo napisao", a to
pitanje ćemo postavljati svaki put kad nešto krene naopako.

Postojeća zastavica `truncated` i dalje znači „nešto je ispalo zbog plafona",
sad i za veštine. Šta je ušlo vidi se iz `vestina_ids`.

**5. Izbor veština u ovom koraku je prost: sve podobne, redom, dok ima mesta.**
Nema rangiranja po upitu. To je namerno: imamo 14 veština i nijedno merenje
koje bi reklo koje su za koji posao. Rangiranje je zasebna odluka, kad broj
poraste toliko da izbor počne da boli. Dok se to ne desi, prost i vidljiv
redosled je pošteniji od pametnog koji niko ne ume da proveri.

**6. Veština se koristi kao znanje, ne prepisuje se.** Rečenica iz
`apps/content/service.py` („Kontekst iz memorije koristi kao znanje, ne
prepisuj ga doslovno") proširuje se tako da pokriva i veštine — iz istog
razloga iz kog ADR-0074 tačka 3 traži da u bazi stoji naš opis postupka a ne
doslovan prepis izvora.

## Šta se ovim NE menja

`retrieval.retrieve` i izbor memorije ostaju netaknuti. Veštine se dodaju
pored, ne umesto.

`brif.build()` za pisca koda ostaje kakav jeste. On već dobija veštine svojim
putem; dva puta do istog skladišta su za sada u redu, a spajanje ta dva je
zasebna odluka koja se ne donosi usput.

Plafoni memorije po profilu (`PROFILE_MEMORY_TOKENS`) ostaju isti. Veštine
dobijaju svoj prostor povrh toga, pa ukupan paket raste — to je svesno
plaćeno: bolje duži prompt nego agent koji radi bez znanja koje imamo.

Ništa se ne menja u tome ko sme da objavi. Spoljne radnje stoje do GO odluke.
