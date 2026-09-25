# Poslušnik za zadatke — ADR-0038

Ovaj direktorijum je jedino mesto u projektu koje dodiruje Docker. To nije slučajno.

## Zašto van aplikacije

`docker.sock` je root na hostu. Da ga dobije `web` ili neki worker, svaka greška u
Django kodu postala bi root na mašini — a zaštićene zone iz ADR-0034 dekor, jer se do
njih stiže ispod aplikacije. Zato poslušnik:

- živi kao systemd jedinica, pod korisnikom koji je u grupi `docker`;
- prima **samo `task_id`** preko API-ja;
- ništa što je agent napisao ne prosleđuje kao komandu, ime, putanju ni zastavicu;
- pokreće potprocese bez ljuske i bez nasleđenog okruženja.

Aplikacija Docker ne vidi i ne treba da ga vidi.

## Šta se vrti po zadatku

`docker-compose.zadatak.yml` diže dva kontejnera na mreži sa `internal: true`:

- **`baza`** — Postgres u `tmpfs`, nestaje sa zadatkom;
- **`kapije`** — slika aplikacije, montiran radni primerak, vrti `kapije.sh`.

Na toj mreži nema rute ka internetu, nema produkcijske baze, Redisa, MinIO-a ni
volumena `secrets`. Nijedan port ne izlazi na host.

Kapije koje se vrte su iste četiri koje vrtimo rukom: `pytest`, `ruff`,
`canon_lint`, `makemigrations --check`. Gotovo = sve četiri zelene (ADR-0035 §3).

## Dve vrednosti koje se moraju proveriti pre puštanja

`PERSONA_REPO` mora da pokazuje na pravi repozitorijum na serveru
(`/home/mm/apps/mm-persona-os`), a `PERSONA_API` na adresu koja se sa hosta
zaista vidi. Servis `web` **ne objavljuje port na host** — ispred njega je Caddy,
pa poslušnik ide kroz `https://os.webkorporacija.com/api/v1` kao i svaki drugi
klijent. Obe vrednosti su 25.09. prvo bile napisane po pretpostavci i obe bi
oborile poslušnika (ADR-0033).

## Instalacija

```
sudo mkdir -p /etc/mm-persona-os
sudo install -m 600 /dev/null /etc/mm-persona-os/runner.env
```

U taj fajl ide jedan red — `PERSONA_TOKEN=…`, i ne piše se rukom. Pravi ga
`manage.py poslusnik --napravi --u <fajl>` unutar kontejnera, pa se prenosi na host:

```
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py poslusnik --napravi --u /tmp/runner.env
docker compose -f docker-compose.prod.yml cp web:/tmp/runner.env /tmp/runner.env
sudo install -m 600 -o root -g root /tmp/runner.env /etc/mm-persona-os/runner.env
rm -f /tmp/runner.env
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web rm -f /tmp/runner.env
```

Token se nigde ne ispisuje na ekran (ADR-0026, ADR-0039 §4).

```
sudo cp deploy/runner/mm-runner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mm-runner
journalctl -u mm-runner -f
```

## Šta ovde NIJE pokriveno testovima

Logika provere zakrpe jeste — `tests/test_zakrpa.py`. Ovaj direktorijum je
okruženje, i proverava se puštanjem, ne `pytest`-om. Zato prvi zadatak koji prođe
kroz njega ide uz čoveka pored ekrana.
