# ADR-0118 — Prilozi inkrement 2: slike i PDF, agent ih vidi

- **Status:** prihvaćen (19.10.2026.)
- **Povod:** Inkrement 1 (ADR-0115) prima vezu i tekstualni fajl. Slika i PDF se
  odbijaju. Vlasnik hoće da pošalje fotografiju ili dokument i da ga agent
  **zaista vidi**, ne da mu se opiše.
- **Prethodi:** ADR-0115 (prilozi inc 1), ADR-0009 (gateway, lokalni šablon kao
  poslednji član), ADR-0106 (direktor procenjuje), ADR-0078 (fajl→model, zvuk)
- **Menja:** `apps/llm_gateway/gateway.py` (vizuelni blokovi),
  `apps/orchestration/razgovor.py` (`posalji`/`razmisli`/`_koraci` nose media),
  `apps/content/steps.py` (`content.draft` učitava media), `apps/content/service.py`
  (`draft` prosleđuje media), `console/views.py` (`_obradi_priloge` prima sliku/PDF),
  testovi.

## Odluka

**1. `generate(..., media=[...])` — content postaje lista blokova.** Kad media
nema, content ostaje običan string (sve postojeće ponašanje netaknuto). Uz
media:
- **Anthropic:** `image` blok (base64, `image/png|jpeg|webp|gif`) i `document`
  blok (base64, `application/pdf`) pre teksta.
- **OpenAI-compatible:** `image_url` sa `data:` URI za slike; PDF toj ruti ide
  kao napomena (ne podržava ga).
- **Lokalni šablon i svaka ruta koja ne vidi dati tip:** prilog postaje
  **tekstualna napomena** u promptu („[prilog: naziv — slika/PDF, nije prosleđen
  modelu]"). Sistem radi i bez spoljnog modela, simulacija ostaje determinističa.

**2. Slika/PDF stiže na dve tačke.** Direktorova procena (PLANNING) i pisanje
nacrta (CONTENT_DRAFT). Media putuje kroz plan kao **`public_id` asseta** u
ulazu koraka (`object_json`); bajtovi se učitavaju iz skladišta tek kad se zove
model. Direktor pravilno usmeri jer vidi; pisac stvarno koristi ono na slici.

**3. Prepis se ne pravi (nastavak ADR-0074 §3).** Za sliku/PDF se u materijal
**ne utka** nikakav tekst — ide modelu kao vizuelni blok. U niti se prilog vidi
kao i dosad (naziv uz čovekovu poruku).

**4. Ulazna vrata.** `_obradi_priloge` prima `image/png,jpeg,webp,gif` i
`application/pdf`; čuva kao `MediaAsset` (`PHOTO` za sliku, `DOCUMENT` za PDF),
`origin=user_owned`. Granice: slika ≤ 5 MB, PDF ≤ 10 MB, najviše 4 priloga po
poruci. Nad granicama — jasna poruka, ništa se ne čuva.

**5. Vision traži spoljnu rutu.** Bez nje (SIMULACIJA / `LLM_EXTERNAL_ENABLED`
isključen) agent dobija napomenu da je prilog stigao ali ga ovim putem ne vidi —
pošteno, bez izmišljanja (ADR-0033). Kad vlasnik upali spoljnu vision rutu,
isti kod počne da vidi, bez izmene.

## Van obima

Zvuk/transkripcija (ADR-0078 ostaje zaseban). Više od 4 priloga po poruci.
Automatsko seckanje PDF-a na stranice (šalje se ceo, u okviru granica).

## Rizik i provera

Jezgro `gateway.py` je kritično i pokriveno; promena je **aditivna** (media
podrazumevano prazna → stari put bajt-identičan). Pun set od četiri kapije +
novi testovi: lokalna napomena (deterministička), i oblik Anthropic/ OpenAI
content liste bez mreže (preko `pozivalac`/`only`).
