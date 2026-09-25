# ADR-0039 — Tri tačke za poslušnika i njegov nalog

- **Status:** prihvaćen (25.09.2026.)
- **Prethodi:** ADR-0038 (izvršilac i zakrpa), ADR-0035 (model zadatka),
  ADR-0026 (ključevi u fajlu, ne u ćaskanju), ADR-0004 (API i uloge)
- **Canon:** §8.1–8.2 (putanje), §8.5 (obavezni header-i), §15.1 (šest uloga)

## Problem

ADR-0038 je opisao poslušnika i njegov kod je napisan — ali **protiv API-ja koji ne
postoji.** Da je instaliran, vrteo bi se u prazno i javljao 404 svakih dvadeset
sekundi. To je moj propust i upisan je ovde poimenice, po ADR-0033.

Druga polovina problema je nalog. Poslušnik radi na mašini koja vrti tuđi kod. Token
sa svim pravima na takvoj mašini nije token nego problem.

## Odluka

### 1. Poslušnik je sistemski nalog, ne sedma uloga

Canon §15.1 ima šest uloga i ostaje šest. Poslušnik je `svc_runner` — servisni nalog
po već postojećoj konvenciji (`svc_` prefiks, principal `service:runner`) — u Django
grupi `runner`. **Nijedna Canon uloga mu se ne dodeljuje**, pa `roles_of()` za njega
vraća prazan skup.

### 2. Zatvoreno podrazumevano

Ovo je suština, ne detalj. `HasAnyRole` do sada je puštao svakog prijavljenog na
poglede bez `required_roles`. Za poslušnika to ne važi: nalog u grupi `runner`
**ne prolazi nigde** osim na pogledima koji izričito nose `allow_runner = True`.

Provera stoji **pre** provere uloga, pa i kad bi neko nalogu dodao ulogu, poslušnik
i dalje ne bi mogao nigde drugde. Danas su otvorene tačno tri tačke.

### 3. Tri tačke, svaka namerno uska

| Tačka | Šta daje | Zašto baš toliko |
|---|---|---|
| `GET /tasks/queued` | **samo spisak `task_id`** | da vrati putanju ili komandu, poslušnik bi postao mesto gde agentov tekst utiče na to šta se izvršava |
| `GET /tasks/{id}/work` | zakrpa **samo ako je `ACCEPTED`**, i `base_sha` | odbijena zakrpa je zapis o agentu, ne posao — ne izlazi iz sistema |
| `POST /tasks/{id}/gate` | upis ishoda jedne kapije | poslušnik ne zatvara zadatak, ne menja putanje, ne dodeljuje poverenje |

„Gotovo" ostaje odluka koju donosi `zadaci.finish` nad zelenim kapijama (ADR-0035 §3).
Poslušnik samo meri i prijavljuje.

### 4. Token se ne ispisuje na ekran

`manage.py poslusnik --napravi --u /etc/mm-persona-os/runner.env` upisuje token u fajl
`0600` i na ekran ispisuje samo putanju i poslednja četiri znaka. Razlog je praktičan:
Slobodan slika terminal, a ključ na slici je ključ u tuđim rukama. Isto pravilo kao za
ključeve agenata (ADR-0026).

Komanda bez `--u` se odbija — nema „samo ovaj put na ekran".

### 5. `api/base.py` ide u zaštićene zone

To je kapija dozvola. Agent koji je menja menja ono što ga ograničava, a to je tačno
ono što ADR-0034 §5.1 zabranjuje. Propust je što do sada nije bio na spisku.

## Nalaz koji je ispao usput

Prvi test kapije vratio je `400`: Canon §8.5 traži `X-Request-ID` i `traceparent` na
svakom zahtevu koji menja stanje — a **poslušnik ih nije slao**. Da je test išao
prečicom umesto pravim putem kroz API, ovo bi se videlo tek na serveru. Popravljeno na
oba mesta.

## Šta je odbačeno

- **Sedma Canon uloga.** Poslušnik nije uloga nego nalog sa jednim poslom.
- **Da poslušnik zatvara zadatak** kad su sve kapije zelene. Zelene kapije nisu
  ispravnost (ADR-0038 §6).
- **Token u `.env.prod`** ili na ekranu.
- **Da `queued` vraća i zakrpu**, da se uštedi jedan poziv. Uštedelo bi jedan poziv i
  potrošilo granicu.

## Posledice

- `api/base.py`: `RUNNER_GROUP`, `is_runner()`, `allow_runner` — zatvoreno podrazumevano.
- `api/views/zadaci.py` + tri rute; `contracts/openapi/persona-os-v1.yaml` regenerisan.
- `manage.py poslusnik --napravi | --stanje`.
- `policy/capabilities.yaml`: `api/base.py` u `protected_paths`.
- Sledeće: prvi pravi prolaz kroz poslušnika, uz čoveka pored ekrana (ADR-0038).
