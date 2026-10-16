# ADR-0101 — Veštine za paket bira sektor persone, ne azbuka

- **Status:** prihvaćen (16.10.2026.)
- **Povod:** Korpus je istog dana narastao sa 28 na 452 veštine. U paket i
  dalje ulazi devet, i to uvek istih devet — one koje su azbučno prve.
- **Prethodi:** ADR-0017 (organizacija), ADR-0074, ADR-0096 (tačka 5),
  ADR-0095, ADR-0059
- **Menja:** `apps/memory/models.py` (novo polje `sector`), migracija
  `0010`, `apps/memory/vestine.py`, komanda `vestina`,
  `apps/memory/context.py`, `apps/memory/embeddings.py`,
  `apps/memory/retrieval.py`.
- **Canon:** §3.11 (poverenje je odvojeno od organizacije — i ovde ostaje)

## Izmereno

| Šta | Vrednost |
|---|---|
| veština u bazi posle uvoza | 452 (`vestina --spisak`, 454 reda sa zaglavljem) |
| veština u paketu (Jovan, `content_draft`) | 9 |
| plafon veština za taj profil | 1000 tokena (`PROFILE_VESTINE_TOKENS`) |
| `truncated` | `True` |
| veštine koje su ušle | identičnih devet kao pre uvoza 424 nove |

ADR-0096 tačka 5 je svesno ostavio izbor prostim: „sve podobne, azbučnim
redom". Dok ih je bilo 28, to je bilo bezazleno. Sa 452 to znači da 443
veštine stoje u bazi i ne vidi ih niko.

## Odluka

**1. Izvor znanja zna kom sektoru pripada.** Novo polje
`KnowledgeSource.sector`. Vokabular nije nov — to su `Department.code` iz
ADR-0017 (`UPRAVA`, `MARKETING`, `RAZVOJ`, `FINANSIJE`, …). Druga podela se
ne izmišlja: organizacija već postoji i već kaže ko šta radi.

**2. Prazan sektor znači „za sve".** Naši sopstveni korpusi (ADR-ovi,
kućna pravila) nemaju sektor i treba da stignu svakome.

**3. Vrednost se proverava pri uvozu, po `Department.code`.** Izmišljen
sektor se odbija pre upisa. Inače bi se greška otkrila tek tako što agent
ostane bez veština, a niko ne bi znao zašto.

**4. Sektor je šesto polje koje čovek donosi pri svakom uvozu** (ADR-0095),
pa se pri ponovnom uvozu osvežava. Isti razlog kao za ostalih pet.

**5. Redosled u paketu je: sektor persone → izvori bez sektora →
poklapanje sa tekstom zadatka → azbuka.** Sektor persone se čita iz
otvorenog primarnog rasporeda (ADR-0017); persona bez rasporeda nema
sektor i za nju vredi stari redosled.

**6. Poklapanje sa zadatkom je namerno TREĆE, ne prvo.** Grubo je i
leksičko (`embeddings.stems`, isti postupak koji već koristi pretraga
memorije). Korpus je engleski, zadaci su srpski — poklapanje je najčešće
nula. Da je prvo po redu, odlučivalo bi ništa. Kad je nula, odlučuje
sektor.

**7. Koreni reči stoje na jednom mestu.** `embeddings.stems` je izvučen iz
`retrieval._stems`, koji ga sada poziva. Dva ista postupka na dva mesta su
dva mesta na kojima se razilaze.

**8. Rangiranje ide u Pythonu, nad svim podobnim redovima.** Sa nekoliko
stotina veština to prolazi. Ovo je prvo mesto koje treba ponovo izmeriti
kad korpus naraste — tada ide ili filter po sektoru u upitu, ili vektori.

## Šta ovo NE radi

Sektor **nije dozvola**. Ista granica kao u ADR-0017: radno mesto ne daje
pravo ni na šta, pa ni ovo. Sektor odlučuje samo šta agent **vidi kao
znanje**; šta sme da uradi i dalje odlučuje isključivo `TrustState`.

Takođe ne rešava duplikate: isto ime veštine iz dva izvora i dalje ulazi
dvaput. Prvo da vidimo da li smeta u radu, pa tek onda da pišemo pravilo.
