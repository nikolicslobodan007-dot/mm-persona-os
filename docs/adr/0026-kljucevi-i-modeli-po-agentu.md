# ADR-0026 — Ključevi i modeli po agentu

- **Status:** prihvaćen
- **Datum:** 24.09.2026.
- **Prethodi:** ADR-0009 (LLM Gateway), ADR-0013 (ključ po agentu), ADR-0025 (konzola)
- **Canon:** §13.2 (rutiranje modela), §14.3 (tajne se ne drže u bazi), §16.4 (curenje memorije)

## Problem

Svaki ključ je do sada ulazio kroz `.env.prod`: `nano`, pa rebuild, pa provera.
Za jednog agenta to je minut. Za deset hiljada agenata i desetak provajdera to
nije posao koji iko radi.

Uz to, svi agenti su delili isti spisak ruta. Mila i Jovan pišu isti tip
teksta, ali klasifikacija poruke i nacrt objave nemaju razloga da idu na isti
model koji odgovara kupcu — a razlika u ceni između modela je red veličine.

## Odluka

### Ključ ide u fajl, referenca u bazu

Ključ se unosi **u konzoli**, na kartici agenta „Modeli i ključevi". Odatle:

- vrednost se upisuje u **fajl sa pravima 0600** (`AGENT_SECRETS_DIR`, docker
  volume `secrets`), koji nije deo slike i koji baza ne vidi;
- u bazu ide samo `file:` referenca, oznaka i **poslednja četiri znaka**;
- vrednost se **nikad ne vraća** — ni u konzolu, ni u API, ni u log. Jedini
  koji je čita je gateway, u trenutku poziva.

Zašto ne u bazu, kad bi bilo jednostavnije: `pg_dump` ide svake noći, Hetzner
pravi dnevne kopije, a bazu čita sedam procesa. Jedan ukraden dump bio bi svih
ključeva svih agenata odjednom. Zato u tabeli stoji i **CHECK** koji odbija red
čiji `credential_ref` ne počinje sa `env:` ili `file:` — pravilo nije stvar
discipline nego baze.

Postavljanje i uklanjanje ključa idu u audit kao `WARNING`, bez vrednosti.
Uklanjanje briše i fajl.

### Ruta po agentu

`AgentRoute` je **pokazivač na postojeću `LLMRoute`**, ne nova vrsta rute: cena,
`data_training_allowed` i ostali uslovi ostaju na jednom mestu, a agent bira
samo koje i kojim redom.

Redosled je: **agentove rute → firmine rute → lokalni šablon.** Agentova ruta ne
traži da je ruta uključena za celu firmu — tako jedan agent sme da koristi
model koji ostali nemaju, a da ga niko ne nasledi kroz rezervu.

### Nov provajder bez izmene koda

`LLMRoute.base_url` nosi adresu API-ja. Adresa nije tajna, pa sme u bazu.
Uz `is_openai_compatible`, koji postoji od ADR-0009, to znači da OpenRouter,
Groq, DeepSeek, Mistral i slični rade kroz postojeći put:

```
manage.py llm_route add --provider openrouter --model mistral-small \
    --base-url https://openrouter.ai/api/v1 --ne-trenira --in-usd 0.2 --out-usd 0.6
```

### Šta ostaje kako je bilo

**Provajder koji sme da uči na našim podacima se i dalje odbija — za svaku
svrhu.** U razgovoru je bilo predloženo da se besplatni modeli dozvole za javni
sadržaj, a zabrane za poštu. Pri pisanju koda se pokazalo da to ne stoji: prompt
za `content_draft` **nosi memorijski kontekst persone** (ADR-0006), a memorija
je tačno ono što Canon §16.4 štiti. „Javni" je tekst na izlazu, ne na ulazu.
Zato pravilo ostaje celo, a ušteda se traži kod jeftinih modela **koji ne
treniraju** — a takvih ima dovoljno.

### Provajder se bira, ne kuca

Prvi ključ unet u konzoli otišao je pod imenom `antropic` — bez „h". Ključ je
uredno sačuvan, ali ga nijedna ruta ne traži, pa ga niko nikad ne bi
upotrebio, a greška se nigde ne bi videla.

Zato je polje sada **padajući spisak provajdera koji stvarno imaju rutu**, uz
slobodno polje za provajdera koji rutu još nema. A ključ čiji provajder ne
odgovara nijednoj ruti nosi oznaku **„nema rutu — niko ga ne koristi"**.

## Šta je odbačeno

- **Ključ u bazi, makar i šifrovan.** Ključ za dešifrovanje bi morao negde da
  stoji; ako stoji uz bazu, nije zaštita nego utisak zaštite.
- **Prikazivanje ključa nazad u konzoli.** Nijedan razlog nije dovoljan: ko
  treba da zna vrednost, ima je kod provajdera.
- **`tmpfs` za tajne.** Preživeo bi restart procesa, ali ne i rebuild — a
  rebuild je kod nas svakodnevan.
- **Zasebna šifra po agentu za pristup konzoli.** Konzola već traži lozinku i
  TOTP; drugi sloj bi samo naveo na pisanje šifara po papirićima.

## Posledice

- Nov agent i nov provajder se dodaju kroz konzolu, bez `nano`-a i bez rebuild-a.
- Volume `secrets` ulazi u Hetzner kopije diska. To je prihvaćeno: kopija diska
  je već poverljiva, a ključevi i dalje nisu u `pg_dump`-u koji putuje češće.
- Otvoreno: rotacija ključeva po rasporedu i merenje kvaliteta po modelu
  (`content_eval` po agentu) — dolaze kad bude više od dva agenta na jeftinom
  modelu.

## Kod

- `apps/llm_gateway/models.py` — `AgentCredential`, `AgentRoute`, `LLMRoute.base_url`
- `apps/llm_gateway/secrets.py` — `set_key`, `drop_key`, `ref_for`, `touch`
- `apps/llm_gateway/gateway.py` — `routes(purpose, persona)`, `credential_ref`,
  `_external_allowed`
- `console/views.py` — `persona_key`, `persona_route`, `_modeli`
- `console/templates/console/persona.html` — kartica „Modeli i ključevi"
- `docker-compose.prod.yml` — volume `secrets` na web i sva tri workera
- `tests/test_agent_models.py` (11 provera), `tests/test_console.py::TestKljuceviUKonzoli`
