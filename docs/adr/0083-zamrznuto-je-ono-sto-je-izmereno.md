# ADR-0083 — Zamrznuto je ono što je izmereno

- **Status:** prihvaćen (12.10.2026.)
- **Povod:** Pri proveri Aiderovog kaveza se videlo da produkcija vrti **Django
  6.1.2**, a ceo naš zapis govori o **5.2**. Niko tu odluku nije doneo.
- **Prethodi:** ADR-0082 (aider u kavezu), ADR-0035 (kapije), ADR-0033 (pravilo
  nula)
- **Menja:** nov fajl `constraints.txt`; `Dockerfile` ga kopira i primenjuje.
- **Canon:** §7.3

## Šta se desilo

`pyproject.toml` zavisnosti nemaju gornju granicu: `django>=5.0`, `celery>=5.4`,
`psycopg>=3.2`. Svako pečenje slike razrešava zavisnosti iznova i sme da povuče
najnovije. Nije odlutao samo Django — izmereno je stanje celog spiska:

| paket | u slici | donja granica u `pyproject.toml` |
|---|---|---|
| Django | **6.1.2** | `>=5.0` |
| djangorestframework | 3.18.3 | `>=3.15` |
| celery | 5.6.3 | `>=5.4` |
| psycopg | 3.3.6 | `>=3.2` |
| redis | 8.1.0 | `>=5.0` |
| pgvector | 0.5.0 | `>=0.3` |
| boto3 | 1.43.108 | `>=1.35` |
| gunicorn | 26.2.0 | `>=22.0` |
| pytest | 9.1.1 | `>=8.0` |
| ruff | 0.16.10 | `>=0.5` |

Koliko je taj pomak star, ne zna se i neće se izmišljati.

## Izmereno pre odluke

Kapije puštene rukom nad tom slikom (`deploy/runner/docker-compose.zadatak.yml`,
isti postupak koji vrti poslušnik): **1232 prošla, 1 preskočen, sve četiri
zelene.** Brojka se slaže red po red: 1226 pre 12.10., +2 nova i 1 izmenjen test
u `test_brif.py` → 1228, +4 iz `test_transcribe.py` → 1232.

**Dakle pomak nije ništa slomio.** Opasnost nije u verziji nego u tome što o
njoj niko nije odlučio.

## Odluka

Uvodi se `constraints.txt` — 51 paket sa tačnim verzijama, dobijen `pip
freeze`-om iz kontejnera u kom su kapije bile zelene. `Dockerfile` ga primenjuje:

```
COPY pyproject.toml constraints.txt ./
RUN pip install -e ".[dev]" -c constraints.txt
```

Podela posla između dva fajla je cela poenta:

- **`pyproject.toml`** kaže **šta nam treba** — donje granice, namera;
- **`constraints.txt`** kaže **šta je izmereno zeleno** — tačne verzije, činjenica.

Do danas je samo prvi fajl postojao, pa je namera tiho glumila činjenicu.

Verzija se u `constraints.txt` menja **namerno i uz merenje**: izmeni red, ispeci
sliku, pusti kapije rukom. Nikad zato što je neko pečenje povuklo novije.

## Ostajemo na 6.1, i zašto

Izmereno sa zvanične stranice projekta i `endoflife.date`:

| | 5.2 LTS | 6.1 |
|---|---|---|
| izašao | 02.04.2025. | 05.08.2026. |
| ispravke grešaka | **završene 03.12.2025.** | do 30.04.2027. |
| bezbednosne zakrpe | do 30.04.2028. | do 31.12.2027. |

„LTS" ovde ne znači ono što zvuči: 5.2 više ne dobija ispravke grešaka, samo
bezbednosne zakrpe, i to četiri meseca duže. Naša 6.1 je jedina od te dve koja
se još popravlja, i na njoj je 1232 testa zeleno. Povratak na 5.2 značio bi
obaranje celog izmerenog spiska u stanje koje nismo izmerili.

**Obaveza koja iz ovoga sledi:** `6.2 LTS` izlazi u aprilu 2027, pre nego što
ijednoj od ove dve istekne bezbednosna podrška. Prelazak se planira tada, kao
odluka, ne kao posledica pečenja.

## Šta ovo ne rešava

Aiderov kavez (`/opt/aider`) ima svoje zavisnosti i **nije pod ovim
ograničenjima** — tamo verziju drži `aider-chat==0.86.2` u `Dockerfile`-u
(ADR-0082). To je namerno: dva okruženja, dva zamrzavanja, nijedno ne vuče ono
drugo.
