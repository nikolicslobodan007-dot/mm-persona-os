# ADR-0086 — Šav za Aidera: broj se ne čita sa ekrana

- **Status:** prihvaćen (13.10.2026.)
- **Povod:** ADR-0081 je tražio tri merenja pre šava. ADR-0085 je zatvorio dva
  (gde se vrti, trošak po pokušaju). Ostao je treći — **zapis** — i on je ceo
  sadržaj ovog ADR-a.
- **Prethodi:** ADR-0085 (Aider je napisao zakrpu), ADR-0081 (pisac sme da bude
  tuđi), ADR-0082 (aider u kavezu), ADR-0062 (učinak agenta), ADR-0044 (pisac),
  ADR-0033 (pravilo nula)
- **Menja:** ništa u kodu danas. Utvrđuje oblik šava i imenuje jedan kvar koji
  se ovim ADR-om **ne** rešava.
- **Canon:** §7.3, §10.4

## Moja greška, prvo

13.10. sam predložio ADR za kurs dolara, pod pretpostavkom da u knjigu ulazi
cena koju provajder prijavljuje. Izmerio sam pre pisanja i pretpostavka je pala.
`apps/llm_gateway/gateway.py:218`:

```
micro = (input_price_micro_eur_per_1k * tin + output_price_micro_eur_per_1k * tout) / 1000
```

Cena je **naša** konfiguracija po ruti, u µEUR, pomnožena brojem tokena. Dolara
nema nigde u lancu. `CostLedger` već nosi `source_currency="EUR"`, `fx_rate=1`,
`fx_date` — polja za kurs postoje i namerno stoje na jedinici.

**Dakle ADR za kurs ne treba.** Aiderovih $0,50 iz ADR-0085 nije podatak za
knjigu nego provera sa strane. ADR-0033 važi i za mene.

## Izmereno: tačan broj postoji

`/opt/aider/lib/python*/site-packages/aider/coders/base_coder.py`, redovi
2000–2029, pročitani a ne pretpostavljeni:

```
if completion and hasattr(completion, "usage") and completion.usage is not None:
    prompt_tokens      = completion.usage.prompt_tokens
    completion_tokens  = completion.usage.completion_tokens
    cache_hit_tokens   = ... prompt_cache_hit_tokens / cache_read_input_tokens
    cache_write_tokens = ... cache_creation_input_tokens
    self.message_tokens_sent     += prompt_tokens
    self.message_tokens_received += completion_tokens
tokens_report = f"Tokens: {format_tokens(self.message_tokens_sent)} sent"
```

Tri činjenice iz toga:

1. Broj dolazi **pravo iz `usage` objekta provajdera**, isto odakle ga uzima i
   naš `_call_external`.
2. Zaokruživanje nastaje tek u `format_tokens()` **pri ispisu**. `114k sent` sa
   ekrana 13.10. je ukras, ne podatak. Tačan broj stoji u
   `message_tokens_sent` / `message_tokens_received`, a zbir po sesiji u
   `total_tokens_sent` / `total_tokens_received` (red 2106).
3. Aider broji **keš odvojeno** — `cache_read_input_tokens` i
   `cache_creation_input_tokens`.

## Odluka

**1. Šav ostaje tamo gde ga je ADR-0081 stavio — u `pisac.pokusaj()` — ali poziv
ide kroz `llm_gateway`, ne pored njega.**

Danas `pokusaj()` zove `gateway.generate(...)`. Umesto da pored toga nikne drugi
put do modela, uvodi se **druga ulazna tačka u istom modulu**, koja radi isti
posao istim redom:

| korak | ko ga radi danas | ko ga radi u šavu |
|---|---|---|
| izbor rute | `gateway.routes(purpose, persona)` | isto |
| dozvola (`PROVIDER_MAY_TRAIN`, ključ persone, `LLM_EXTERNAL_ENABLED`) | `gateway._external_allowed` | **isto** |
| poziv modela | `gateway._call_external` | pokretač Aidera |
| cena | `gateway._cost_cents(route, tin, tout)` | isto |
| zapis (`PromptRecord`, `CostLedger`, `LLMUsage`) | `gateway._record` | isto |

Ovo nije ukras nego uslov. `PROVIDER_MAY_TRAIN` — „provajder koji sme da uči na
našim podacima se odbija za svaku svrhu" — stoji u `_external_allowed`. Alat koji
sam zove model mimo te provere srušio bi pravilo koje je starije od njega.

**2. Aider se pokreće kao poseban proces, iz svog kaveza, preko našeg pokretača.**

ADR-0082 drži Aiderovih 107 zavisnosti van okruženja aplikacije, pa ga `pisac`
ne sme uvesti kao biblioteku. Ali Pajton iz kaveza (`/opt/aider/bin/python`) sme
da izvrši **naš** fajl. Taj pokretač uveze Aiderov `Coder`, odradi posao i upiše
JSON na putanju koju mu `pisac` zada:

```
{"model": "...", "tokens_sent": N, "tokens_received": M,
 "cache_read": K, "cache_write": L, "finish": "...", "files": [...]}
```

`pisac` čita taj fajl. **Ekran se ne parsira.** Zaokružen broj nikad ne ulazi u
knjigu.

**3. Zastavice ostaju kako su izmerene 13.10.:** `--no-git`,
`use_temperature: false`, ključ iz `/secrets/anthropic_<persona>.key`, bez mreže
ka bilo čemu osim provajderu. Menjaju se kad za promenu postoji merenje, ne pre.

## Kvar koji ovaj ADR imenuje i ne rešava

**Naša cena ne poznaje keš.** `LLMRoute` ima dve cene — ulaz i izlaz.
`LLMUsage` ima dva polja — `input_tokens` i `output_tokens`. Kod Anthropic-a je
pročitani keš višestruko jeftiniji od svežeg ulaza, a upisani keš skuplji.

Posledica je merljiva i ide u oba smera: keširan poziv se u našoj knjizi
naplaćuje **punom** cenom ulaza, a poziv koji keš tek upisuje **premalo**. Dok
smo zvali model bez keša, razlika je bila nula. Aider keš koristi, pa od prvog
poziva kroz šav razlika postaje stvarna.

Ovo se ne krpi usput jer dira cenovnik ruta i oblik `LLMUsage` — dakle meru
učinka agenta (ADR-0062). Ide u svoj ADR, sa izmerenim cenovnikom provajdera, a
dotle se u zapisu **mora videti** koliko je tokena bilo keširano, makar cena bila
računata po staroj formuli. Bolje tačan broj uz poznatu grešku nego uredan broj
koji krije da greška postoji.

## Šta ovo ne menja

Ništa iznad ni ispod šava. Zadatak, persona, poverenje po putanji, zaštićene
zone, `zakrpa --proveri`, četiri kapije u izolovanom kontejneru, grana koja se
otvara tek kad su zelene — sve ostaje gde jeste. Aider i dalje piše **predlog**.

## Šta ostaje neizmereno

Mapa repozitorijuma. 13.10. je bila ugašena (`--no-git`), pa je ceo dobitak došao
od oblika izmene, ne od mape (ADR-0085). Dok se mapa ne izmeri sa upaljenim
`git`-om u slici, ADR-0080 (`MIN_IZVOD_PROCENAT`) ostaje na snazi i `_izvod` se
ne dira.

## Dopuna, izmereno isto veče: keš brojači ne postoje na objektu

Zakrpu po ovom ADR-u napisao je Aider (P-00027, zadatak
`TSK-01M4TTDGWKY9H9YKGQBED5OAFZ`), i uz nju je **sam prijavio** da tačni nazivi
keš brojača nisu izmereni u brifu, nego pogođeni. Provereno je, i sumnja je bila
opravdana — stvar je čak gora od toga.

`base_coder.py`, pročitano:

```
2003–2006:  cache_hit_tokens = ...        cache_write_tokens = ...
2012:       self.message_tokens_sent += cache_write_tokens
2026:       tokens_report += f", {format_tokens(cache_write_tokens)} cache write"
2095:       cost += cache_write_tokens * input_cost_per_token * 1.25
```

Keš brojači su **lokalne promenljive unutar funkcije**. Ulaze u zbir poslatih
tokena, u tekst izveštaja i u Aiderov račun — ali se **nigde ne čuvaju na
objektu `Coder`**. Nema `total_tokens_cache_read` ni ičega sličnog.

Posledica: pokretač će za `cache_read` i `cache_write` uvek upisati `null`.
To **nije** mana njegovog koda — `null` znači „nije izmereno", i to je istina.
Broj prosto nije dostupan putem `return_coder`.

Dve činjenice koje ovo merenje usput daje, i obe idu u ADR o ceni:

1. **Red 2095:** upisani keš se naplaćuje `input_cost × 1.25`. To je izmeren
   množilac, ne procena.
2. **Red 2012:** `cache_write_tokens` **ulazi** u `message_tokens_sent`. Dakle
   broj poslatih tokena nije čist ulaz. Naš `_cost_cents` bi taj deo naplatio po
   običnoj ulaznoj ceni, dok provajder traži 1,25×. Greška ide u našu korist pri
   čitanju keša, a protiv nas pri upisu.

Da bi se keš ikad izmerio, pokretač bi morao da uhvati odgovor pre Aidera — to
je druga odluka i ne donosi se ovde.

**Ovo je ujedno prvi put da je agent prijavio sopstvenu neizmerenu
pretpostavku pre nego što ga je iko pitao.** ADR-0033 nije stigao do njega kroz
priručnik nego kroz brif, i proradio je.
